#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for alertmanager."""

import logging
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Tuple, cast
from urllib.parse import urlparse

import yaml
from alertmanager import (
    ConfigFileSystemState,
    ConfigUpdateFailure,
    WorkloadManager,
    WorkloadManagerError,
)
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    RemoteConfigurationRequirer,
)
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerProvider
from charms.catalogue_k8s.v1.catalogue import CatalogueConsumer, CatalogueItem
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.karma_k8s.v0.karma_dashboard import KarmaProvider
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    ResourceRequirements,
    adjust_resource_requirements,
)
from charms.observability_libs.v1.cert_handler import CertHandler
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from charms.tempo_k8s.v2.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from config_builder import ConfigBuilder, ConfigError
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    OpenedPort,
    Relation,
    WaitingStatus,
)
from ops.pebble import PathError, ProtocolError  # type: ignore

logger = logging.getLogger(__name__)


@trace_charm(
    tracing_endpoint="tracing_endpoint",
    server_cert="server_cert_path",
    extra_types=(
        AlertmanagerProvider,
        CertHandler,
        IngressPerAppRequirer,
        KubernetesComputeResourcesPatch,
        RemoteConfigurationRequirer,
    ),
)
class AlertmanagerCharm(CharmBase):
    """A Juju charm for alertmanager."""

    # Container name must match metadata.yaml
    # Layer name is used for the layer label argument in container.add_layer
    # Service name matches charm name for consistency
    _container_name = _service_name = "alertmanager"
    _relations = SimpleNamespace(
        alerting="alerting", peer="replicas", remote_config="remote_configuration"
    )
    _ports = SimpleNamespace(api=9093, ha=9094)

    # path, inside the workload container, to the alertmanager and amtool configuration files
    # the amalgamated templates file goes in the same folder as the main configuration file
    _config_path = "/etc/alertmanager/alertmanager.yml"
    _web_config_path = "/etc/alertmanager/alertmanager-web-config.yml"
    _amtool_config_path = "/etc/amtool/config.yml"
    _templates_path = "/etc/alertmanager/templates.tmpl"

    _server_cert_path = "/etc/alertmanager/alertmanager.cert.pem"
    _key_path = "/etc/alertmanager/alertmanager.key.pem"
    _ca_cert_path = "/usr/local/share/ca-certificates/cos-ca.crt"

    def __init__(self, *args):
        super().__init__(*args)
        self.container = self.unit.get_container(self._container_name)

        self.server_cert = CertHandler(
            self,
            key="am-server-cert",
            sans=[socket.getfqdn()],
        )
        self.framework.observe(
            self.server_cert.on.cert_changed,  # pyright: ignore
            self._on_server_cert_changed,
        )

        self.ingress = IngressPerAppRequirer(
            self,
            port=self.api_port,
            scheme=lambda: urlparse(self._internal_url).scheme,
            strip_prefix=True,
            redirect_https=True,
        )
        self.framework.observe(self.ingress.on.ready, self._handle_ingress)  # pyright: ignore
        self.framework.observe(self.ingress.on.revoked, self._handle_ingress)  # pyright: ignore

        self.alertmanager_provider = AlertmanagerProvider(
            self,
            relation_name=self._relations.alerting,
            external_url=self._internal_url,  # TODO See 'TODO' below, about external_url
        )

        self.grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="alertmanager",
            source_url=self._external_url,
        )
        self.karma_provider = KarmaProvider(self, "karma-dashboard")
        self.remote_configuration = RemoteConfigurationRequirer(self)

        self.set_ports()

        self.resources_patch = KubernetesComputeResourcesPatch(
            self,
            self._container_name,
            resource_reqs_func=self._resource_reqs_from_config,
        )
        self.framework.observe(
            self.resources_patch.on.patch_failed, self._on_k8s_patch_failed  # pyright: ignore
        )

        # Self-monitoring
        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="self-metrics-endpoint",
            jobs=self.self_scraping_job,
            refresh_event=[
                self.on.update_status,
                self.ingress.on.ready,  # pyright: ignore
                self.ingress.on.revoked,  # pyright: ignore
                self.on["ingress"].relation_changed,
                self.on["ingress"].relation_departed,
                self.server_cert.on.cert_changed,  # pyright: ignore
            ],
        )
        self._tracing = TracingEndpointRequirer(self, protocols=["otlp_http"])

        self.catalog = CatalogueConsumer(charm=self, item=self._catalogue_item)

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.alertmanager_workload = WorkloadManager(
            self,
            container_name=self._container_name,
            peer_addresses=self._get_peer_addresses(),
            api_port=self.api_port,
            ha_port=self._ports.ha,
            web_external_url=self._internal_url,
            config_path=self._config_path,
            web_config_path=self._web_config_path,
            tls_enabled=self._is_tls_ready,
            cafile=self._ca_cert_path if Path(self._ca_cert_path).exists() else None,
        )
        self.framework.observe(
            # The workload manager too observes pebble ready, but still need this here because
            # of the common exit hook (otherwise would need to pass the common exit hook as
            # a callback).
            self.on.alertmanager_pebble_ready,  # pyright: ignore
            self._on_pebble_ready,
        )
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Remote configuration events
        self.framework.observe(
            self.remote_configuration.on.remote_configuration_changed,  # pyright: ignore
            self._on_remote_configuration_changed,
        )

        # Peer relation events
        self.framework.observe(
            self.on[self._relations.peer].relation_joined, self._on_peer_relation_joined
        )
        self.framework.observe(
            self.on[self._relations.peer].relation_changed, self._on_peer_relation_changed
        )

        # Action events
        self.framework.observe(
            self.on.show_config_action, self._on_show_config_action  # pyright: ignore
        )
        self.framework.observe(
            self.on.check_config_action, self._on_check_config  # pyright: ignore
        )

    def set_ports(self):
        """Open necessary (and close no longer needed) workload ports."""
        planned_ports = {
            OpenedPort("tcp", self._ports.api),
            OpenedPort("tcp", self._ports.ha),
        }
        actual_ports = self.unit.opened_ports()

        # Ports may change across an upgrade, so need to sync
        ports_to_close = actual_ports.difference(planned_ports)
        for p in ports_to_close:
            self.unit.close_port(p.protocol, p.port)

        new_ports_to_open = planned_ports.difference(actual_ports)
        for p in new_ports_to_open:
            self.unit.open_port(p.protocol, p.port)

    @property
    def _catalogue_item(self) -> CatalogueItem:
        return CatalogueItem(
            name="Alertmanager",
            icon="bell-alert",
            url=self._external_url,
            description=(
                "Alertmanager receives alerts from supporting applications, such as "
                "Prometheus or Loki, then deduplicates, groups and routes them to "
                "the configured receiver(s)."
            ),
        )

    @property
    def self_scraping_job(self):
        """The self-monitoring scrape job."""
        # We assume that scraping, especially self-monitoring, is in-cluster.
        # This assumption is necessary because the local CA signs CSRs with FQDN as the SAN DNS.
        # If prometheus were to scrape an ingress URL instead, it would error out with:
        # x509: cannot validate certificate.
        metrics_endpoint = urlparse(self._internal_url.rstrip("/") + "/metrics")
        metrics_path = metrics_endpoint.path
        # Render a ':port' section only if it is explicit (e.g. 9093; without an explicit port, the
        # port is deduced from the scheme).
        port_str = (":" + str(metrics_endpoint.port)) if metrics_endpoint.port is not None else ""
        target = f"{metrics_endpoint.hostname}{port_str}"
        config = {
            "scheme": metrics_endpoint.scheme,
            "metrics_path": metrics_path,
            "static_configs": [{"targets": [target]}],
        }

        return [config]

    def _resource_reqs_from_config(self) -> ResourceRequirements:
        limits = {
            "cpu": self.model.config.get("cpu"),
            "memory": self.model.config.get("memory"),
        }
        requests = {"cpu": "0.25", "memory": "200Mi"}
        return adjust_resource_requirements(limits, requests, adhere_to_requests=True)

    def _on_k8s_patch_failed(self, event: K8sResourcePatchFailedEvent):
        self.unit.status = BlockedStatus(str(event.message))

    def _handle_ingress(self, _):
        if url := self.ingress.url:
            logger.info("Ingress is ready: '%s'.", url)
        else:
            logger.info("Ingress revoked.")
        self._common_exit_hook()

    def _on_check_config(self, event: ActionEvent) -> None:
        """Runs `amtool check-config` inside the workload."""
        try:
            stdout, stderr = self.alertmanager_workload.check_config()
        except WorkloadManagerError as e:
            return event.fail(str(e))

        if not stdout and stderr:
            return event.fail(stderr)

        event.set_results({"result": stdout, "error-message": stderr, "valid": not stderr})
        return None

    def _on_show_config_action(self, event: ActionEvent):
        """Hook for the show-config action."""
        event.log(f"Fetching {self._config_path}")
        if not self.alertmanager_workload.is_ready:
            event.fail("Container not ready")

        filepaths = self._render_manifest().manifest.keys()

        try:
            results = [
                {
                    "path": filepath,
                    "content": str(self.container.pull(filepath).read()),
                }
                for filepath in filepaths
            ]
            content = self.container.pull(self._config_path)
            # juju requires keys to be lowercase alphanumeric (can't use self._config_path)
            event.set_results(
                {
                    "path": self._config_path,
                    "content": str(content.read()),
                    # This already includes the above, but keeping both for backwards compat.
                    "configs": str(results),
                }
            )
        except (ProtocolError, PathError) as e:
            event.fail(str(e))

    @property
    def api_port(self) -> int:
        """Get the API port number to use for alertmanager (default: 9093)."""
        return self._ports.api

    @property
    def peer_relation(self) -> Optional["Relation"]:
        """Helper function for obtaining the peer relation object.

        Returns: peer relation object
        (NOTE: would return None if called too early, e.g. during install).
        """
        return self.model.get_relation(self._relations.peer)

    def _get_remote_config(self) -> Optional[Tuple[Optional[dict], Optional[str]]]:
        remote_config, remote_templates = self.remote_configuration.config()
        if remote_config:
            templates = "\n".join(remote_templates) if remote_templates else None
            return remote_config, templates
        return None

    def _get_local_config(self) -> Optional[Tuple[Optional[dict], Optional[str]]]:
        config = self.config["config_file"]
        if config:
            local_config = yaml.safe_load(cast(str, config))
            local_templates = cast(str, self.config["templates_file"]) or None
            return local_config, local_templates
        return None

    def _get_raw_config_and_templates(
        self,
    ) -> Tuple[Optional[dict], Optional[str]]:
        # block if multiple config sources configured
        if self._get_remote_config() and self._get_local_config():
            logger.error("unable to use config from config_file and relation at the same time")
            raise ConfigUpdateFailure("Multiple configs detected")
        # if no config provided, use default config with a placeholder receiver
        if compound_config := self._get_remote_config():
            config, templates = compound_config
        elif compound_config := self._get_local_config():
            config, templates = compound_config
        else:
            config = None
            templates = None

        return config, templates

    def _render_manifest(self) -> ConfigFileSystemState:
        raw_config, raw_templates = self._get_raw_config_and_templates()

        # Note: A free function (with many args) would have the same functionality.
        config_suite = (
            ConfigBuilder(api_port=self.api_port)
            .set_config(raw_config)
            .set_tls_server_config(
                cert_file_path=self._server_cert_path, key_file_path=self._key_path
            )
            .set_templates(raw_templates, self._templates_path)
            .build()
        )

        return ConfigFileSystemState(
            {
                self._config_path: config_suite.alertmanager,
                self._web_config_path: config_suite.web,
                self._templates_path: config_suite.templates,
                self._amtool_config_path: config_suite.amtool,
                self._server_cert_path: self.server_cert.server_cert,
                self._key_path: self.server_cert.private_key,
                self._ca_cert_path: self.server_cert.ca_cert,
            }
        )

    def _common_exit_hook(self, update_ca_certs: bool = False) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.resources_patch.is_ready():
            if isinstance(self.unit.status, ActiveStatus) or self.unit.status.message == "":
                self.unit.status = WaitingStatus("Waiting for resource limit patch to apply")
            return

        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        # Make sure the external url is valid
        if external_url := self._external_url:
            parsed = urlparse(external_url)
            if not (parsed.scheme in ["http", "https"] and parsed.hostname):
                # This shouldn't happen
                logger.error(
                    "Invalid external url: '%s'; must include scheme and hostname.",
                    external_url,
                )
                self.unit.status = BlockedStatus(
                    f"Invalid external url: '{external_url}'; must include scheme and hostname."
                )
                return

        # TODO Conditionally update with the external URL if it's a CMR, or rely on "recv-ca-cert"
        #  on the prometheus side.
        #  - https://github.com/canonical/operator/issues/970
        #  - https://github.com/canonical/prometheus-k8s-operator/issues/530,
        self.alertmanager_provider.update(external_url=self._internal_url)

        self.ingress.provide_ingress_requirements(
            scheme=urlparse(self._internal_url).scheme, port=self.api_port
        )
        self._scraping.update_scrape_job_spec(self.self_scraping_job)

        if self.peer_relation:
            # Could have simply used `socket.getfqdn()` here and add the path when reading this
            # relation data, but this way it is more future-proof in case we change from ingress
            # per app to ingress per unit.
            self.peer_relation.data[self.unit]["private_address"] = self._internal_url

        self.karma_provider.target = self._external_url

        # Update config file
        try:
            self.alertmanager_workload.update_config(self._render_manifest())
        except (ConfigUpdateFailure, ConfigError) as e:
            self.unit.status = BlockedStatus(str(e))
            return

        if update_ca_certs:
            self._update_ca_certs()

        # Update pebble layer
        self.alertmanager_workload.update_layer()

        # Reload or restart the service
        try:
            self.alertmanager_workload.reload()
        except ConfigUpdateFailure as e:
            self.unit.status = BlockedStatus(str(e))
            return

        self.catalog.update_item(item=self._catalogue_item)

        self.unit.status = ActiveStatus()

    def _on_server_cert_changed(self, _):
        self._common_exit_hook(update_ca_certs=True)

    def _on_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook()

    def _on_peer_relation_joined(self, _):
        """Event handler for replica's RelationChangedEvent."""
        self._common_exit_hook()

    def _on_peer_relation_changed(self, _):
        """Event handler for replica's RelationChangedEvent.

        `relation_changed` is needed in addition to `relation_joined` because when a second unit
        joins, the first unit must be restarted and provided with the second unit's IP address.
        when the first unit sees "joined", it is not guaranteed that the second unit already has
        an IP address.
        """
        self._common_exit_hook()

    def _on_remote_configuration_changed(self, _):
        """Event handler for remote configuration's RelationChangedEvent."""
        self._common_exit_hook()

    def _on_update_status(self, _):
        """Event handler for UpdateStatusEvent.

        Logs list of peers, uptime and version info.
        """
        try:
            status = self.alertmanager_workload.api.status()
            logger.info(
                "alertmanager %s is up and running (uptime: %s); "
                "cluster mode: %s, with %d peers",
                status["versionInfo"]["version"],
                status["uptime"],
                status["cluster"]["status"],
                len(status["cluster"]["peers"]),
            )
        except ConnectionError as e:
            logger.error("Failed to obtain status: %s", str(e))

        # Calling the common hook to make sure a single unit set its IP in case all events fired
        # before an IP address was ready, leaving UpdateStatue as the last resort.
        self._common_exit_hook()

    def _on_upgrade_charm(self, _):
        """Event handler for replica's UpgradeCharmEvent."""
        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same, and
        # the config may need update. Calling the common hook to update.
        self._common_exit_hook()

    def _update_ca_certs(self):
        # Workload container
        self.container.exec(["update-ca-certificates", "--fresh"]).wait()

        # Charm container
        ca_cert_path = Path(self._ca_cert_path)
        if self.server_cert.ca_cert:
            ca_cert_path.parent.mkdir(exist_ok=True, parents=True)
            ca_cert_path.write_text(self.server_cert.ca_cert)  # pyright: ignore
        else:
            ca_cert_path.unlink(missing_ok=True)
        subprocess.run(["update-ca-certificates", "--fresh"], check=True)

    def _get_peer_addresses(self) -> List[str]:
        """Create a list of HA addresses of all peer units (all units excluding current).

        The returned addresses include the hostname, HA port number and path, but do not include
        scheme (http).
        """
        addresses = []
        if pr := self.peer_relation:
            for unit in pr.units:  # pr.units only holds peers (self.unit is not included)
                if api_url := pr.data[unit].get("private_address"):
                    parsed = urlparse(api_url)
                    if not (parsed.scheme in ["http", "https"] and parsed.hostname):
                        # This shouldn't happen
                        logger.error(
                            "Invalid peer address in relation data: '%s'; skipping. "
                            "Address must include scheme (http or https) and hostname.",
                            api_url,
                        )
                        continue
                    # Drop scheme and replace API port with HA port
                    addresses.append(f"{parsed.hostname}:{self._ports.ha}{parsed.path}")

        return addresses

    def _is_tls_ready(self) -> bool:
        """Returns True if the workload is ready to operate in TLS mode."""
        return (
            self.container.can_connect()
            and self.container.exists(self._server_cert_path)
            and self.container.exists(self._key_path)
            and self.container.exists(self._ca_cert_path)
        )

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of the alertmanager api server.

        If an external (public) url is set, add in its path.
        """
        scheme = "https" if self._is_tls_ready() else "http"
        return f"{scheme}://{socket.getfqdn()}:{self._ports.api}"

    @property
    def _external_url(self) -> str:
        """Return the externally-reachable (public) address of the alertmanager api server."""
        return self.ingress.url or self._internal_url

    @property
    def tracing_endpoint(self) -> Optional[str]:
        """Otlp http endpoint for charm instrumentation."""
        if self._tracing.is_ready():
            return self._tracing.get_endpoint("otlp_http")
        return None

    @property
    def server_cert_path(self) -> Optional[str]:
        """Server certificate path for tls tracing."""
        return self._server_cert_path


if __name__ == "__main__":
    main(AlertmanagerCharm)

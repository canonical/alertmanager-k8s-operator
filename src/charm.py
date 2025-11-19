#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for alertmanager."""

import logging
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Tuple, cast
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    RemoteConfigurationRequirer,
)
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerProvider
from charms.catalogue_k8s.v1.catalogue import CatalogueConsumer, CatalogueItem
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshConsumer, UnitPolicy
from charms.karma_k8s.v0.karma_dashboard import KarmaProvider
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    ResourceRequirements,
    adjust_resource_requirements,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer, charm_tracing_config
from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
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

from alertmanager import (
    ConfigFileSystemState,
    ConfigUpdateFailure,
    WorkloadManager,
    WorkloadManagerError,
)
from config_builder import ConfigBuilder, ConfigError

logger = logging.getLogger(__name__)


@dataclass
class TLSConfig:
    """TLS configuration received by the charm over the `certificates` relation."""

    server_cert: str
    ca_cert: str
    private_key: str


@trace_charm(
    tracing_endpoint="_charm_tracing_endpoint",
    server_cert="_charm_tracing_ca_cert",
    extra_types=(
        AlertmanagerProvider,
        TLSCertificatesRequiresV4,
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
        self._fqdn = socket.getfqdn()

        self._csr_attributes = CertificateRequestAttributes(
            # the `common_name` field is required but limited to 64 characters.
            # since it's overridden by sans, we can use a short,
            # constrained value like app name.
            common_name=self.app.name,
            sans_dns=frozenset((self._fqdn,)),
        )
        self._cert_requirer = TLSCertificatesRequiresV4(
            charm=self,
            relationship_name="certificates",
            certificate_requests=[self._csr_attributes],
        )
        self.framework.observe(
            self._cert_requirer.on.certificate_available,  # pyright: ignore
            self._on_certificate_available,
        )

        self.ingress = IngressPerAppRequirer(
            self,
            port=self.api_port,
            scheme=self._scheme,
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
            source_url=self.ingress.url or self._service_url,
            is_ingress_per_app=True, # We want only one alertmanager datasource (unit) to be listed in grafana.
            refresh_event=[
                self.ingress.on.ready,
                self.ingress.on.revoked,
                self.on.update_status,
                self._cert_requirer.on.certificate_available,
            ],
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
            self.resources_patch.on.patch_failed,
            self._on_k8s_patch_failed,  # pyright: ignore
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
                self._cert_requirer.on.certificate_available,  # pyright: ignore
            ],
        )
        self._tracing = TracingEndpointRequirer(self, protocols=["otlp_http"])
        self._charm_tracing_endpoint, self._charm_tracing_ca_cert = charm_tracing_config(
            self._tracing, self._ca_cert_path
        )

        self.catalog = CatalogueConsumer(charm=self, item=self._catalogue_item)

        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                UnitPolicy(
                    relation="alerting",
                    ports=[self.api_port],
                ),
                UnitPolicy(
                    relation="grafana-source",
                    ports=[self.api_port],
                ),
                UnitPolicy(
                    relation="self-metrics-endpoint",
                    ports=[self.api_port],
                ),
            ],
        )

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)

        peer_ha_netlocs = [
            f"{hostname}:{self._ports.ha}"
            for hostname in self._get_peer_hostnames(include_this_unit=False)
        ]

        self.alertmanager_workload = WorkloadManager(
            self,
            container_name=self._container_name,
            peer_netlocs=peer_ha_netlocs,
            api_port=self.api_port,
            ha_port=self._ports.ha,
            web_external_url=self._external_url,
            web_route_prefix="/",
            config_path=self._config_path,
            web_config_path=self._web_config_path,
            tls_enabled=lambda: self._tls_available,
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
            self.on.show_config_action,
            self._on_show_config_action,  # pyright: ignore
        )
        self.framework.observe(
            self.on.check_config_action,
            self._on_check_config,  # pyright: ignore
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
        api_endpoints = {"Alerts": "/api/v2/alerts"}

        return CatalogueItem(
            name="Alertmanager",
            icon="bell-alert",
            url=self._external_url,
            description=(
                "Alertmanager receives alerts from supporting applications, such as "
                "Prometheus or Loki, then deduplicates, groups and routes them to "
                "the configured receiver(s)."
            ),
            api_docs="https://github.com/prometheus/alertmanager/blob/main/api/v2/openapi.yaml",
            api_endpoints={
                key: f"{self._external_url}{path}" for key, path in api_endpoints.items()
            },
        )

    @property
    def self_scraping_job(self):
        """The self-monitoring scrape job."""
        # We assume that scraping, especially self-monitoring, is in-cluster.
        # This assumption is necessary because the local CA signs CSRs with FQDN as the SAN DNS.
        # If prometheus were to scrape an ingress URL instead, it would error out with:
        # x509: cannot validate certificate.
        peer_api_netlocs = [
            f"{hostname}:{self._ports.api}"
            for hostname in self._get_peer_hostnames(include_this_unit=True)
        ]

        config = {
            "scheme": self._scheme,
            "metrics_path": "/metrics",
            "static_configs": [{"targets": peer_api_netlocs}],
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
                if self.container.exists(filepath)
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

            # If `juju config` is executed like this `config_file=am.yaml` instead of
            # `config_file=@am.yaml` local_config will be the string `am.yaml` instead
            # of its content (dict).
            if not isinstance(local_config, dict):
                msg = f"Unable to set config from file. Use juju config {self.unit.name} config_file=@FILENAME"
                logger.error(msg)
                raise ConfigUpdateFailure(msg)

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
        tls_config = self._tls_config

        return ConfigFileSystemState(
            {
                self._config_path: config_suite.alertmanager,
                self._web_config_path: config_suite.web,
                self._templates_path: config_suite.templates,
                self._amtool_config_path: config_suite.amtool,
                self._server_cert_path: tls_config.server_cert if tls_config else None,
                self._key_path: tls_config.private_key if tls_config else None,
                self._ca_cert_path: tls_config.ca_cert if tls_config else None,
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

        if update_ca_certs:
            self._update_ca_certs()

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

        self.grafana_source_provider.update_source(self._external_url)

        self.ingress.provide_ingress_requirements(scheme=self._scheme, port=self.api_port)
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

    def _on_certificate_available(self, _):
        self._common_exit_hook(update_ca_certs=True)

    def _on_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook(update_ca_certs=True)

    def _on_start(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook(update_ca_certs=True)

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
                "alertmanager %s is up and running (uptime: %s); cluster mode: %s, with %d peers",
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
        ca_cert_path = Path(self._ca_cert_path)
        if tls_config := self._tls_config:
            ca_cert_path.parent.mkdir(exist_ok=True, parents=True)
            ca_cert_path.write_text(tls_config.ca_cert)
        else:
            ca_cert_path.unlink(missing_ok=True)

        # Workload container
        self.container.exec(["update-ca-certificates", "--fresh"], timeout=30).wait()
        # Charm container
        subprocess.run(["update-ca-certificates", "--fresh"], check=True)

    def _get_peer_hostnames(self, include_this_unit=True) -> List[str]:
        """Returns a list of the hostnames of the peer units.

        An example of the return format is:
          ["alertmanager-1.alertmanager-endpoints.am.svc.cluster.local"]
        """
        addresses = []
        if include_this_unit:
            addresses.append(self._internal_url)
        if pr := self.peer_relation:
            for unit in pr.units:  # pr.units only holds peers (self.unit is not included)
                if address := pr.data[unit].get("private_address"):
                    addresses.append(address)

        # Save only the hostname part of the address
        # Sort the hostnames in case their order is not guaranteed, to reduce unnecessary updates
        hostnames = sorted([urlparse(address).hostname for address in addresses])

        return hostnames

    @property
    def _tls_config(self) -> Optional[TLSConfig]:
        certificates, key = self._cert_requirer.get_assigned_certificate(
            certificate_request=self._csr_attributes
        )
        if not (key and certificates):
            return None
        return TLSConfig(certificates.certificate.raw, certificates.ca.raw, key.raw)

    @property
    def _tls_available(self) -> bool:
        return bool(self._tls_config)

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of the alertmanager api server."""
        return f"{self._scheme}://{self._fqdn}:{self._ports.api}"

    @property
    def _service_url(self) -> str:
        """Return the FQDN DNS-based in-cluster (private) address of the service for Alertmanager.

        Since our goal is to ensure that we only send one datasource to Grafana when we have multiple units, we can't use the socket FQDN because that would include the AM unit e.g. `http://am-0.am-endpoints.otel.svc.cluster.local:9093`.
        The service URL as defined will remove the pod unit so (when ingress missing) the request goes to the K8s service at: http://am-endpoints.otel.svc.cluster.local:9093
        The service will then load balance between the units.
        TODO: This assumes that the FQDN is the interal FQDN for the socket and that the pod unit is always on the left side of the first ".". If those change, this code will need to be updated.
        """
        fqdn = self._fqdn
        try:
            fqdn = fqdn.split(".", 1)[1]
        except IndexError:
            pass

        return f"{self._scheme}://{fqdn}:{self._ports.api}"

    @property
    def _external_url(self) -> str:
        """Return the externally-reachable (public) address of the alertmanager api server."""
        return self.ingress.url or self._internal_url

    @property
    def _scheme(self) -> str:
        return "https" if self._tls_available else "http"


if __name__ == "__main__":
    main(AlertmanagerCharm)

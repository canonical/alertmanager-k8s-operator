#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for alertmanager."""

import hashlib
import logging
import socket
from typing import List, Optional, cast
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerProvider
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.karma_k8s.v0.karma_dashboard import KarmaProvider
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v1.ingress import IngressPerAppRequirer
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, Relation
from ops.pebble import ChangeError, Layer, PathError, ProtocolError

from alertmanager_client import Alertmanager, AlertmanagerBadResponse

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class ConfigUpdateFailure(RuntimeError):
    """Custom exception for failed config updates."""


class AlertmanagerCharm(CharmBase):
    """A Juju charm for alertmanager.

    Attributes:
        api: an API client instance for communicating with the alertmanager workload
                server
    """

    # Container name is automatically determined from charm name
    # Layer name is used for the layer label argument in container.add_layer
    # Service name matches charm name for consistency
    _container_name = _layer_name = _service_name = "alertmanager"
    _relation_name = "alerting"
    _peer_relation_name = "replicas"  # must match metadata.yaml peer role name
    _api_port = 9093  # port to listen on for the web interface and API
    _ha_port = 9094  # port for HA-communication between multiple instances of alertmanager

    # path, inside the workload container, to the alertmanager and amtool configuration files
    # the amalgamated templates file goes in the same folder as the main configuration file
    _config_path = "/etc/alertmanager/alertmanager.yml"
    _templates_path = "/etc/alertmanager/templates.tmpl"
    _amtool_config_path = "/etc/amtool/config.yml"

    # path, inside the workload container for alertmanager data, e.g. 'nflogs', 'silences'.
    _storage_path = "/alertmanager"

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(config_hash=None, launched_with_peers=False)

        self.ingress = IngressPerAppRequirer(self, port=self.api_port)
        self.framework.observe(self.ingress.on.ready, self._handle_ingress)
        self.framework.observe(self.ingress.on.revoked, self._handle_ingress)

        # The `_external_url` property is passed as a callable so that the charm library code
        # always uses up-to-date context.
        # This arg is needed because in case of a custom event (e.g. ingress ready) or a re-emit,
        # the charm won't be re-initialized with an updated external url.
        # Also, coincidentally, unit tests would otherwise fail because harness doesn't
        # reinitialize the charm between core events.
        self.alertmanager_provider = AlertmanagerProvider(
            self,
            self._relation_name,
            self._api_port,
            external_url=lambda: AlertmanagerCharm._external_url.fget(self),  # type: ignore
        )
        self.api = Alertmanager(port=self._api_port, web_route_prefix=self.web_route_prefix)

        self.grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="alertmanager",
            source_url=self._external_url,
        )
        self.karma_provider = KarmaProvider(self, "karma-dashboard")

        self.service_patcher = KubernetesServicePatch(
            self,
            [
                (f"{self.app.name}", self._api_port, self._api_port),
                (f"{self.app.name}-ha", self._ha_port, self._ha_port),
            ],
        )

        # Self-monitoring
        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="self-metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{self._api_port}"]}]}],
        )

        self.container = self.unit.get_container(self._container_name)

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.alertmanager_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Peer relation events
        self.framework.observe(
            self.on[self._peer_relation_name].relation_joined, self._on_peer_relation_joined
        )
        self.framework.observe(
            self.on[self._peer_relation_name].relation_changed, self._on_peer_relation_changed
        )

        # Action events
        self.framework.observe(self.on.show_config_action, self._on_show_config_action)

    def _handle_ingress(self, event):
        if url := self.ingress.url:
            logger.info("Ingress is ready: '%s'.", url)
        else:
            logger.info("Ingress revoked.")
        self._common_exit_hook()

    def _on_show_config_action(self, event: ActionEvent):
        """Hook for the show-config action."""
        event.log(f"Fetching {self._config_path}")
        if not self.container.can_connect():
            event.fail("Container not ready")

        try:
            content = self.container.pull(self._config_path)
            # juju requires keys to be lowercase alphanumeric (can't use self._config_path)
            event.set_results({"path": self._config_path, "content": content.read()})
        except (ProtocolError, PathError) as e:
            event.fail(str(e))

    @property
    def api_port(self) -> int:
        """Get the API port number to use for alertmanager (default: 9093)."""
        return self._api_port

    @property
    def peer_relation(self) -> Optional["Relation"]:
        """Helper function for obtaining the peer relation object.

        Returns: peer relation object
        (NOTE: would return None if called too early, e.g. during install).
        """
        return self.model.get_relation(self._peer_relation_name)

    def _alertmanager_layer(self) -> Layer:
        """Returns Pebble configuration layer for alertmanager."""

        def _command():
            """Returns full command line to start alertmanager."""
            peer_addresses = self._get_peer_addresses()

            # cluster listen address - empty string disables HA mode
            listen_address_arg = "" if len(peer_addresses) == 0 else f"0.0.0.0:{self._ha_port}"

            # The chosen port in the cluster.listen-address flag is the port that needs to be
            # specified in the cluster.peer flag of the other peers.
            # Assuming all replicas use the same port.
            # Sorting for repeatability in comparing between service layers.
            peer_cmd_args = " ".join(
                sorted([f"--cluster.peer={address}" for address in peer_addresses])
            )
            return (
                f"alertmanager "
                f"--config.file={self._config_path} "
                f"--storage.path={self._storage_path} "
                f"--web.listen-address=:{self._api_port} "
                f"--cluster.listen-address={listen_address_arg} "
                f"--web.external-url={self._external_url} "
                f"{peer_cmd_args}"
            )

        return Layer(
            {
                "summary": "alertmanager layer",
                "description": "pebble config layer for alertmanager",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "summary": "alertmanager service",
                        "command": _command(),
                        "startup": "enabled",
                    }
                },
            }
        )

    def _restart_service(self) -> bool:
        """Helper function for restarting the underlying service.

        Returns:
            True if restart succeeded; False otherwise.
        """
        logger.info("Restarting service %s", self._service_name)

        if not self.container.can_connect():
            logger.error("Cannot (re)start service: container is not ready.")
            return False

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not exist,
        if not self.container.get_plan().services.get(self._service_name):
            logger.error("Cannot (re)start service: service does not (yet) exist.")
            return False

        self.container.restart(self._service_name)

        # Update "launched with peers" flag.
        # The service should be restarted when peers joined if this is False.
        plan = self.container.get_plan()
        service = plan.services.get(self._service_name)
        self._stored.launched_with_peers = "--cluster.peer" in service.command

        return True

    def _update_layer(self) -> bool:
        """Update service layer to reflect changes in peers (replicas).

        Args:
          restart: a flag indicating if the service should be restarted if a change was detected.

        Returns:
          True if anything changed; False otherwise
        """
        overlay = self._alertmanager_layer()
        plan = self.container.get_plan()

        if self._service_name not in plan.services or overlay.services != plan.services:
            self.container.add_layer(self._layer_name, overlay, combine=True)
            try:
                # If a config is invalid then alertmanager would exit immediately.
                # This would be caught by pebble (default timeout is 30 sec) and a ChangeError
                # would be raised.
                self.container.replan()
                return True
            except ChangeError as e:
                logger.error(
                    "Failed to replan; pebble plan: %s; %s",
                    self.container.get_plan().to_dict(),
                    str(e),
                )
                return False

        return False

    @property
    def _default_config(self) -> dict:
        return {
            "global": {"http_config": {"tls_config": {"insecure_skip_verify": True}}},
            "route": {
                "group_wait": "30s",
                "group_interval": "5m",
                "repeat_interval": "1h",
                "receiver": "dummy",
            },
            "receivers": [
                {"name": "dummy", "webhook_configs": [{"url": "http://127.0.0.1:5001/"}]}
            ],
        }

    def _update_config(self) -> None:
        """Update alertmanager.yml config file to reflect changes in configuration.

        After pushing a new config, a hot-reload is attempted. If hot-reload fails, the service is
        restarted.

        Raises:
          ConfigUpdateFailure, if failed to update configuration file.
        """
        # update amtool config file
        amtool_config = yaml.safe_dump(
            {"alertmanager.url": f"http://localhost:{self.api_port}" + self.web_route_prefix}
        )
        self.container.push(self._amtool_config_path, amtool_config, make_dirs=True)

        # if no config provided, use default config with a dummy receiver
        config = yaml.safe_load(self.config["config_file"]) or self._default_config

        if config.get("templates", []):
            logger.error(
                "alertmanager config file must not have a 'templates' section; "
                "use the 'templates' config option instead."
            )
            raise ConfigUpdateFailure(
                "Invalid config file: use charm's 'templates' config option instead"
            )

        # add templates, if any
        if templates := self.config["templates_file"]:
            config["templates"] = [f"{self._templates_path}"]
            self.container.push(self._templates_path, templates, make_dirs=True)

        # add juju topology to "group_by"
        route = cast(dict, config.get("route", {}))
        route["group_by"] = list(
            set(route.get("group_by", [])).union(
                ["juju_application", "juju_model", "juju_model_uuid"]
            )
        )
        config["route"] = route

        config_yaml = yaml.safe_dump(config)
        config_hash = sha256(config_yaml)

        if config_hash == self._stored.config_hash:
            logger.debug("no change in config")
            return

        logger.debug("config changed")
        self._push_config_and_reload(config_yaml)
        self._stored.config_hash = config_hash

    def _push_config_and_reload(self, config_yaml):
        """Push config into workload container, and trigger a hot-reload (or service restart).

        Args:
            config_yaml: contents of the new config file.

        Raises:
            ConfigUpdateFailure, if config update fails.
        """
        self.container.push(self._config_path, config_yaml, make_dirs=True)

        # Obtain a "before" snapshot of the config from the server.
        # This is different from `config` above because alertmanager adds in a bunch of details
        # such as:
        #
        #   smtp_hello: localhost
        #   smtp_require_tls: true
        #   pagerduty_url: https://events.pagerduty.com/v2/enqueue
        #   opsgenie_api_url: https://api.opsgenie.com/
        #   wechat_api_url: https://qyapi.weixin.qq.com/cgi-bin/
        #   victorops_api_url: https://alert.victorops.com/integrations/generic/20131114/alert/
        #
        # The snapshot is needed to determine if reloading took place.
        try:
            config_from_server_before = self.api.config()
        except AlertmanagerBadResponse:
            config_from_server_before = None

        # Send an HTTP POST to alertmanager to hot-reload the config.
        # This reduces down-time compared to restarting the service.
        try:
            self.api.reload()
        except AlertmanagerBadResponse as e:
            logger.warning("config reload via HTTP POST failed: %s", str(e))
            # hot-reload failed so attempting a service restart
            if not self._restart_service():
                raise ConfigUpdateFailure(
                    "Is config valid? hot reload and service restart failed."
                )

        # Obtain an "after" snapshot of the config from the server.
        try:
            config_from_server_after = self.api.config()
        except AlertmanagerBadResponse:
            config_from_server_after = None

        if config_from_server_before is None or config_from_server_after is None:
            logger.warning("cannot determine if reload succeeded")
        elif config_from_server_before == config_from_server_after:
            logger.warning("config remained the same after a reload")

    def _common_exit_hook(self) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        self.alertmanager_provider.update_relation_data()

        if self.peer_relation:
            # Could have simply used `socket.getfqdn()` here and add the path when reading this
            # relation data, but this way it is more future-proof in case we change from ingress
            # per app to ingress per unit.
            self.peer_relation.data[self.unit]["private_address"] = self._internal_url

        self.karma_provider.target = self._external_url  # TODO: check if this included scheme

        # Update pebble layer
        self._update_layer()

        # Update config file
        try:
            self._update_config()
        except ConfigUpdateFailure as e:
            self.unit.status = BlockedStatus(str(e))
            return

        self.unit.status = ActiveStatus()

    def _on_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        # TODO: what to do if "web_external_url" is invalid
        self._common_exit_hook()

    def _on_start(self, _):
        """Event handler for StartEvent.

        With Juju 2.9.5 encountered a scenario in which pebble_ready and config_changed fired,
        but IP address was not available and the status was stuck on "Waiting for IP address".
        Adding this hook reduce the likelihood of that scenario.
        """
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

    def _on_update_status(self, _):
        """Event handler for UpdateStatusEvent.

        Logs list of peers, uptime and version info.
        """
        try:
            status = self.api.status()
            logger.info(
                "alertmanager %s is up and running (uptime: %s); "
                "cluster mode: %s, with %d peers",
                status["versionInfo"]["version"],
                status["uptime"],
                status["cluster"]["status"],
                len(status["cluster"]["peers"]),
            )
        except AlertmanagerBadResponse as e:
            logger.error("Failed to obtain status: %s", str(e))

        # Calling the common hook to make sure a single unit set its IP in case all events fired
        # before an IP address was ready, leaving UpdateStatue as the last resort.
        self._common_exit_hook()

    def _on_upgrade_charm(self, _):
        """Event handler for replica's UpgradeCharmEvent."""
        # update config hash
        self._stored.config_hash = (
            ""
            if not self.container.can_connect()
            else sha256(yaml.safe_dump(yaml.safe_load(self.container.pull(self._config_path))))
        )

        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same, and
        # the config may need update. Calling the common hook to update.
        self._common_exit_hook()

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
                    if not (parsed.scheme and parsed.hostname):
                        # This shouldn't happen
                        logger.warning(
                            "Invalid peer address in relation data: '%s'; skipping. "
                            "Address must include scheme and hostname.",
                            api_url,
                        )
                        continue
                    # Drop scheme and replace API port with HA port
                    addresses.append(f"{parsed.hostname}:{self._ha_port}{parsed.path}")

        return addresses

    @property
    def web_route_prefix(self) -> str:
        """Return the web route prefix with both a leading and a trailing separator.

        The prefix is determined from the external (public) URL, with the config option
        "web_external_url" taking precedence over the ingress one.
        """
        url = self.model.config.get("web_external_url") or self.ingress.url or ""
        path = urlparse(url).path
        if path and not path.endswith("/"):
            # urlparse("http://a.b/c").path returns 'c' without "/"
            # urljoin will drop the part of the url that does not end with a '/'.
            # Need to make sure it's in place.
            path += "/"

        return path

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of the alertmanager api server.

        If an external (public) url is set, add in its path.
        """
        return f"http://{socket.getfqdn()}:{self._api_port}{self.web_route_prefix}"

    @property
    def _external_url(self) -> str:
        """Return the externally-reachable (public) address of the alertmanager api server."""
        # TODO what to do if "web_external_url" is invalid
        return self.model.config.get("web_external_url") or self.ingress.url or self._internal_url


if __name__ == "__main__":
    main(AlertmanagerCharm, use_juju_for_storage=True)

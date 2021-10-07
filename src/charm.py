#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for alertmanager."""

import hashlib
import logging
from typing import List, Optional

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerProvider
from charms.karma_k8s.v0.karma_dashboard import KarmaProvider
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, Relation
from ops.pebble import Layer, PathError, ProtocolError

from alertmanager_client import Alertmanager, AlertmanagerBadResponse
from kubernetes_service import K8sServicePatch, PatchFailed

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
        self.api = Alertmanager(port=self._api_port)

        self.alertmanager_provider = AlertmanagerProvider(
            self, self._relation_name, self._api_port
        )
        self.karma_provider = KarmaProvider(self, "karma-dashboard")

        self.container = self.unit.get_container(self._container_name)

        # Core lifecycle events
        self.framework.observe(self.on.install, self._on_install)
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
    def peer_relation(self) -> Optional[Relation]:
        """Helper function for obtaining the peer relation object.

        Returns: peer relation object; returns None if called too early, e.g. during install.
        """
        return self.model.get_relation(self._peer_relation_name)

    @property
    def private_address(self) -> Optional[str]:
        """Get the unit's ip address.

        Technically, receiving a "joined" event guarantees an IP address is available. If this is
        called beforehand, a None would be returned.
        When operating a single unit, no "joined" events are visible so obtaining an address is a
        matter of timing in that case.

        This function is still needed in Juju 2.9.5 because the "private-address" field in the
        data bag is being populated by the app IP instead of the unit IP.
        Also in Juju 2.9.5, ip address may be None even after RelationJoinedEvent, for which
        "ops.model.RelationDataError: relation data values must be strings" would be emitted.

        Returns:
          None if no IP is available (called before unit "joined"); unit's ip address otherwise
        """
        # if bind_address := check_output(["unit-get", "private-address"]).decode().strip()
        if bind_address := self.model.get_binding(self._peer_relation_name).network.bind_address:
            bind_address = str(bind_address)
        return bind_address

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

    def _update_layer(self, restart: bool) -> bool:
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

            if restart:
                self._restart_service()

            return True

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
        amtool_config = yaml.safe_dump({"alertmanager.url": f"http://localhost:{self.api_port}"})
        self.container.push(self._amtool_config_path, amtool_config, make_dirs=True)

        # if no config provided, use default config with a dummy receiver
        config = yaml.safe_load(self.config["config_file"]) or self._default_config

        if "templates" in config:
            logger.error(
                "alertmanager config file must not have a 'templates' section; "
                "use the 'templates' config option instead."
            )
            raise ConfigUpdateFailure(
                "Invalid config file: use charm's 'templates' config option instead"
            )

        # add templates, if any
        if templates := self.config["templates_file"]:
            config["templates"] = [f"'{self._templates_path}'"]
            self.container.push(self._templates_path, templates, make_dirs=True)

        # add juju topology to "group_by"
        route = config.get("route", {})
        route["group_by"] = list(
            set(route.get("group_by", [])).union(
                ["juju_application", "juju_model", "juju_model_uuid"]
            )
        )
        config["route"] = route

        config_yaml = yaml.safe_dump(config)
        config_hash = sha256(config_yaml)

        logger.debug(
            "config changed" if config_hash != self._stored.config_hash else "no change",
        )

        if config_hash != self._stored.config_hash:
            self.container.push(self._config_path, config_yaml)

            # Send an HTTP POST to alertmanager to hot-reload the config.
            # This reduces down-time compared to restarting the service.
            try:
                self.api.reload()
                self._stored.config_hash = config_hash
            except AlertmanagerBadResponse as e:
                logger.warning("config reload via HTTP POST failed: %s", str(e))
                # hot-reload failed so attempting a service restart
                if self._restart_service():
                    self._stored.config_hash = config_hash
                else:
                    raise ConfigUpdateFailure(
                        "Is config valid? hot reload and service restart failed."
                    )

    @property
    def api_address(self):
        """Returns the API address (including scheme and port) of the alertmanager server."""
        return f"http://{self.private_address}:{self.api_port}"

    def _patch_k8s_service(self):
        """Fix the Kubernetes service that was setup by Juju with correct port numbers."""
        if self.unit.is_leader():
            service_ports = [
                (f"{self.app.name}", self.api_port, self.api_port),
                (f"{self.app.name}-ha", self._ha_port, self._ha_port),
            ]
            try:
                K8sServicePatch.set_ports(self.app.name, service_ports)
            except PatchFailed as e:
                logger.error("Unable to patch the Kubernetes service: %s", str(e))
            else:
                logger.info("Successfully patched the Kubernetes service")

    def _common_exit_hook(self) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        # Wait for IP address. IP address is needed for forming alertmanager clusters and for
        # related apps' config.
        if not self.private_address:
            self.unit.status = MaintenanceStatus("Waiting for IP address")
            return

        # In the case of a single unit deployment, no 'RelationJoined' event is emitted, so
        # setting IP here.
        # Store private address in unit's peer relation data bucket. This is still needed because
        # the "private-address" field in the data bag is being populated incorrectly.
        # Also, ip address may still be None even after RelationJoinedEvent, for which
        # "ops.model.RelationDataError: relation data values must be strings" would be emitted.
        if self.peer_relation:
            self.peer_relation.data[self.unit]["private_address"] = self.private_address

        self.alertmanager_provider.update_relation_data()
        self.karma_provider.target = self.api_address

        # Update pebble layer
        layer_changed = self._update_layer(restart=False)

        service_running = (
            service := self.container.get_service(self._service_name)
        ) and service.is_running()

        num_peers = len(self.peer_relation.units)

        if layer_changed and (
            not service_running or (num_peers > 0 and not self._stored.launched_with_peers)
        ):
            self._restart_service()

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
        self._common_exit_hook()

    def _on_start(self, _):
        """Event handler for StartEvent.

        With Juju 2.9.5 encountered a scenario in which pebble_ready and config_changed fired,
        but IP address was not available and the status was stuck on "Waiting for IP address".
        Adding this hook reduce the likelihood of that scenario.
        """
        self._common_exit_hook()

    def _on_install(self, _):
        """Event handler for InstallEvent during which we will update the K8s service."""
        self._patch_k8s_service()

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
        # Ensure that older deployments of Alertmanager run the logic to patch the K8s service
        self._patch_k8s_service()

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

        The returned addresses include the HA port number but do not include scheme (http).
        If a unit does not have an address, it will be omitted from the list.
        """
        addresses = []
        if pr := self.peer_relation:
            addresses = [
                f"{address}:{self._ha_port}"
                for unit in pr.units  # pr.units only holds peers (self.unit is not included)
                if (address := pr.data[unit].get("private_address"))
            ]

        return addresses


if __name__ == "__main__":
    main(AlertmanagerCharm, use_juju_for_storage=True)

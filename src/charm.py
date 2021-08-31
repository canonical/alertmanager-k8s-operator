#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for alertmanager."""

import hashlib
import logging
from typing import Dict, List, Optional

import yaml

from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerProvider
from charms.karma_k8s.v0.karma import KarmaConsumer
from flatten_json import unflatten
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    ErrorsWithMessage,
    MaintenanceStatus,
    Relation,
    Unit,
)
from ops.pebble import Layer

from alertmanager_client import Alertmanager, AlertmanagerBadResponse
from config import PagerdutyConfig, PushoverConfig, WebhookConfig
from kubernetes_service import K8sServicePatch, PatchFailed

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


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
    _config_path = "/etc/alertmanager/alertmanager.yml"
    _amtool_config_path = "/etc/amtool/config.yml"

    # path, inside the workload container for alertmanager data, e.g. 'nflogs', 'silences'.
    _storage_path = "/alertmanager"

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(config_hash=None, launched_with_peers=False)
        self.api = Alertmanager(port=self._api_port)

        try:
            workload_version = self.api.version
        except AlertmanagerBadResponse:
            workload_version = "0.0.0"

        self.provider = AlertmanagerProvider(
            self, self._relation_name, self._service_name, workload_version, self._api_port
        )
        self.karma_lib = KarmaConsumer(self, "karma-dashboard", consumes={"karma": ">=0.86"})
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
        if not self.container.is_ready():
            event.fail("Container not ready")

        try:
            content = self.container.pull(self._config_path)
            # juju requires keys to be lowercase alphanumeric (can't use self._config_path)
            event.set_results({"path": self._config_path, "content": content.read()})
        except ErrorsWithMessage as e:
            event.fail(str(e))

    @property
    def api_port(self):
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
        """Helper function for restarting the underlying service."""
        logger.info("Restarting service %s", self._service_name)

        with self.container.is_ready() as c:
            # Check if service exists, to avoid ModelError from being raised when the service does
            # not exist,
            if not c.get_plan().services.get(self._service_name):
                logger.error("Cannot (re)start service: service does not (yet) exist.")
                return False

            c.restart(self._service_name)

            # Update "launched with peers" flag.
            # The service should be restarted when peers joined if this is False.
            plan = self.container.get_plan()
            service = plan.services.get(self._service_name)
            self._stored.launched_with_peers = "--cluster.peer" in service.command

        if not c.completed:
            logger.error("Cannot (re)start service: container is not ready.")
            return False

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
        is_changed = False

        if self._service_name not in plan.services or overlay.services != plan.services:
            is_changed = True
            self.container.add_layer(self._layer_name, overlay, combine=True)

        if is_changed and restart:
            self._restart_service()

        return is_changed

    def _update_config(self) -> bool:
        """Update alertmanager.yml config file to reflect changes in configuration.

        After pushing a new config, a hot-reload is attempted. If hot-reload fails, the service is
        restarted.

        Returns:
          True if unchanged, or if changed successfully; False otherwise
        """
        # Cannot use a period ('.') as a separator because of a mongo/juju issue:
        # https://github.com/canonical/operator/issues/585
        unflattened_config = unflatten(dict(self.config), "::")

        # Only one receiver is supported at the moment; prioritizing pagerduty.
        # If none are valid, populating with a dummy, otherwise alertmanager won't start.
        receiver = (
            PagerdutyConfig.from_dict(unflattened_config["pagerduty"])
            or PushoverConfig.from_dict(unflattened_config["pushover"])
            or WebhookConfig.from_dict(unflattened_config["webhook"])
            or WebhookConfig.from_dict({"url": "http://127.0.0.1:5001/"})  # dummy
        )

        config = {
            "global": {"http_config": {"tls_config": {"insecure_skip_verify": True}}},
            "route": {
                "group_by": ["juju_application", "juju_model", "juju_model_uuid"],
                "group_wait": "30s",
                "group_interval": "5m",
                "repeat_interval": "1h",
                "receiver": receiver["name"],
            },
            "receivers": [receiver],
        }

        config_yaml = yaml.safe_dump(config)
        config_hash = sha256(config_yaml)

        logger.debug(
            "recevier: %s - %s",
            receiver["name"],
            "changed" if config_hash != self._stored.config_hash else "no change",
        )

        success = True
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
                if success := self._restart_service():
                    self._stored.config_hash = config_hash

        # update amtool config file
        amtool_config = yaml.safe_dump({"alertmanager.url": f"http://localhost:{self.api_port}"})
        self.container.push(self._amtool_config_path, amtool_config, make_dirs=True)

        return success

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

    def _common_exit_hook(self) -> bool:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.is_ready():
            # TODO replace with self.container.is_ready() after confirming it indeed obviates
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return False

        # Wait for IP address. IP address is needed for config hot-reload and status updates.
        if not self.private_address:
            self.unit.status = MaintenanceStatus("Waiting for IP address")
            return False

        # In the case of a single unit deployment, no 'RelationJoined' event is emitted, so
        # setting IP here.
        # Store private address in unit's peer relation data bucket. This is still needed because
        # the "private-address" field in the data bag is being populated incorrectly.
        # Also, ip address may still be None even after RelationJoinedEvent, for which
        # "ops.model.RelationDataError: relation data values must be strings" would be emitted.
        if self.peer_relation:
            self.peer_relation.data[self.unit]["private_address"] = self.private_address

        self.provider.update_relation_data()
        self.karma_lib.target = self.api_address

        # Update pebble layer
        # Callees below interact with pebble.
        # Catching pebble exceptions here for a centralized control of the unit status.
        with self.container.is_ready() as c:
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
            if not self._update_config():
                self.unit.status = BlockedStatus("Config update failed. Is config valid?")
                return False

            self.provider.ready()
            self.unit.status = ActiveStatus()

        if not c.completed:
            logger.error("Cannot update layer - container is not ready")
            self.unit.status = BlockedStatus("Container not ready")
            return False

        return True

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
        # Ensure that older deployments of Alertmanager run the logic
        # to patch the K8s service
        self._patch_k8s_service()

        # update config hash
        with self.container.is_ready() as c:
            self._stored.config_hash = sha256(
                yaml.safe_dump(yaml.safe_load(self.container.pull(self._config_path)))
            )

        if not c.completed:
            self._stored.config_hash = ""

        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same
        # Calling the common hook to update IP address to the new one
        self._common_exit_hook()

    def _get_unit_address_map(self) -> Dict[Unit, Optional[str]]:
        """Create a mapping between Unit and its IP address.

        The returned addresses do not include ports nor scheme.
        If an IP address is not available, the corresponding value will be None.
        """
        # For some reason self.peer_relation.units returns an empty set so using `isinstance`
        addresses = {
            unit: data.get("private_address")
            for unit, data in self.peer_relation.data.items()
            if isinstance(unit, Unit)
        }
        return addresses

    def _get_peer_addresses(self) -> List[str]:
        """Create a list of HA addresses of all peer units (all units excluding current).

        The returned addresses include the HA port number but do not include scheme (http).
        If a unit does not have an API, it will be omitted from the list.
        """
        return [
            f"{address}:{self._ha_port}"
            for unit, address in self._get_unit_address_map().items()
            if unit is not self.unit and address is not None
        ]


if __name__ == "__main__":
    main(AlertmanagerCharm, use_juju_for_storage=True)

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import urllib.parse
import urllib.error
from typing import Any, Dict, List, Optional

from kubernetes_service import K8sServicePatch, PatchFailed
import ops
import requests
import yaml
from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerProvider
from charms.karma_k8s.v0.karma import KarmaConsumer
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import ChangeError

import utils
from config import PagerdutyConfig, PushoverConfig, WebhookConfig

from flatten_json import unflatten

logger = logging.getLogger(__name__)


class AlertmanagerAPIClient:
    """Alertmanager HTTP API client."""

    def __init__(self, address: str, port: int, timeout=2.0):
        self.base_url = "http://{}:{}/".format(address, port)
        self.timeout = timeout

    def reload(self) -> bool:
        """Send a POST request to to hot-reload the config.
        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = urllib.parse.urljoin(self.base_url, "/-/reload")
        try:
            response = requests.post(url, timeout=self.timeout)
            logger.debug("config reload via %s: %d %s", url, response.status_code, response.reason)
            return response.status_code == 200 and response.reason == "OK"
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
            logger.debug("config reload error via %s: %s", url, str(e))
            return False

    @staticmethod
    def _get(url: str, timeout) -> Optional[dict]:
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                text = json.loads(response.text)
            else:
                text = None
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            text = None
        return text

    def status(self) -> Optional[dict]:
        url = urllib.parse.urljoin(self.base_url, "/api/v2/status")
        return self._get(url, timeout=self.timeout)

    def silences(self, state: str = None) -> Optional[List[dict]]:
        url = urllib.parse.urljoin(self.base_url, "/api/v2/silences")
        silences = self._get(url, timeout=self.timeout)

        # if GET failed or user did not provide a state to filter by, return as-is (possibly None); else filter by state
        return (
            silences
            if silences is None or state is None
            else [s for s in silences if s.get("status") and s["status"].get("state") == state]
        )

    @property
    def version(self) -> Optional[str]:
        if status := self.status():
            return status["versionInfo"]["version"]
        return None


class AlertmanagerCharm(CharmBase):
    # Container name is automatically determined from charm name
    # Layer name is used for the layer label argument in container.add_layer
    # Service name matches charm name for consistency
    _container_name = _layer_name = _service_name = "alertmanager"
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
        self.container = self.unit.get_container(self._container_name)

        # event observations
        self.framework.observe(self.on.alertmanager_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        self.framework.observe(
            self.on[self._peer_relation_name].relation_joined, self._on_peer_relation_joined
        )
        self.framework.observe(
            self.on[self._peer_relation_name].relation_changed, self._on_peer_relation_changed
        )
        self.framework.observe(
            self.on[self._peer_relation_name].relation_departed, self._on_peer_relation_departed
        )

        self._stored.set_default(
            pebble_ready=False,
            config_hash=None,
            launched_with_peers=False,
        )

        self.provider = AlertmanagerProvider(
            self, self._service_name, self.api_client.version or "0.0.0"
        )
        self.provider.api_port = self._api_port

        self.karma_lib = KarmaConsumer(
            self,
            "karma-dashboard",
            consumes={"karma": ">=0.86"},
        )

        # action observations
        self.framework.observe(self.on.show_config_action, self._on_show_config_action)
        self.framework.observe(self.on.show_silences_action, self._on_show_silences_action)

    def _on_show_config_action(self, event: ActionEvent):
        event.log("Fetching {}".format(self._config_path))
        try:
            content = self.container.pull(self._config_path)
            # ideally would like the key to be self._config_path, but juju requires lowercase alphanumeric
            event.set_results({"path": self._config_path, "content": content.read()})
        except Exception as e:
            event.fail(str(e))
            raise

    def _on_show_silences_action(self, event: ActionEvent):
        event.log("Fetching active silences")
        active_silences = self.api_client.silences("active")
        if active_silences is not None:
            event.set_results({"active-silences": json.dumps(active_silences)})
        else:
            event.fail("Error retrieving silences via alertmanager api server")

    @property
    def api_port(self):
        """Get the API port number to use for alertmanager (default: 9093)."""
        return self._api_port

    @property
    def num_peers(self) -> int:
        """Number of peer units (excluding self)"""
        # For some reason in Juju 2.9.5 `self.peer_relation.units` is an empty set
        return sum(
            isinstance(unit, ops.model.Unit) and unit is not self.unit
            for unit in self.peer_relation.data.keys()
        )

    @property
    def peer_relation(self) -> Optional[ops.model.Relation]:
        # Returns None if called too early, e.g. during install.
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

    def _store_private_address(self):
        """Store private address in unit's peer relation data bucket.

        This function is still needed in Juju 2.9.5 because the "private-address" field in the
        data bag is being populated by the app IP instead of the unit IP.
        Also in Juju 2.9.5, ip address may be None even after RelationJoinedEvent, for which
        "ops.model.RelationDataError: relation data values must be strings" would be emitted.
        """
        self.peer_relation.data[self.unit]["private_address"] = self.private_address

    def _fetch_private_address(self) -> Optional[str]:
        """Fetch private address from unit's peer relation data bucket."""
        if relation := self.peer_relation:
            return relation.data[self.unit].get("private_address")
        return None

    def _alertmanager_layer(self) -> Dict[str, Any]:
        """Returns Pebble configuration layer for alertmanager."""

        def _command():
            """Returns full command line to start alertmanager"""
            peer_addresses = self._get_peer_addresses()

            # cluster listen address - empty string disables HA mode
            listen_address_arg = "" if len(peer_addresses) == 0 else f"0.0.0.0:{self._ha_port}"

            # The chosen port in the cluster.listen-address flag is the port that needs to be
            # specified in the cluster.peer flag of the other peers.
            # Assuming all replicas use the same port.
            # Sorting for repeatability in comparing between service layers.
            peer_cmd_args = " ".join(
                sorted(["--cluster.peer={}".format(address) for address in peer_addresses])
            )
            return (
                "alertmanager "
                "--config.file={} "
                "--storage.path={} "
                "--web.listen-address=:{} "
                "--cluster.listen-address={} "
                "{}".format(
                    self._config_path,
                    self._storage_path,
                    self._api_port,
                    listen_address_arg,
                    peer_cmd_args,
                )
            )

        return {
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

    @property
    def is_service_running(self) -> bool:
        """Helper function for checking if the alertmanager service is running.

        Returns:
          True if the service is running; False otherwise.

        Raises:
          ModelError: If the service is not defined (e.g. layer does not exist).
        """
        return self.container.get_service(self._service_name).is_running()

    def _restart_service(self) -> bool:
        logger.info("Restarting service %s", self._service_name)

        try:
            # if the service does not exist, ModelError will be raised
            if self.is_service_running:
                self.container.stop(self._service_name)
            self.container.start(self._service_name)

            # Update "launched with peers" flag.
            # The service should be restarted when peers joined if this is False.
            plan = self.container.get_plan()
            service = plan.services.get(self._service_name)
            self._stored.launched_with_peers = "--cluster.peer" in service.command
            return True

        except ops.model.ModelError:
            logger.warning("Service does not (yet?) exist; (re)start aborted")
            return False
        except ChangeError as e:
            logger.error("ChangeError: failed to (re)start service: %s", str(e))
            return False
        except Exception as e:
            logger.error("failed to (re)start service: %s", str(e))
            raise

    def _update_layer(self, restart: bool = True) -> bool:
        """Update service layer to reflect changes in peers (replicas).

        Args:
          restart: a flag indicating if the service should be restarted if a change was detected.

        Returns:
          True if anything changed; False otherwise
        """
        overlay = self._alertmanager_layer()

        plan = self.container.get_plan()

        is_changed = False
        # if this unit has just started, the services does not yet exist - using "get"
        service = plan.services.get(self._service_name)
        overlay_command = overlay["services"][self._service_name]["command"]
        logger.info("update layer: overlay command: %s", overlay_command)

        if service is None or service.command != overlay_command:
            is_changed = True
            self.container.add_layer(self._layer_name, overlay, combine=True)

        if is_changed and restart:
            self._restart_service()

        return is_changed

    def _update_config(self, restart_on_failure: bool = True) -> bool:
        """Update alertmanager.yml config file to reflect changes in configuration.

        Args:
          restart_on_failure: a flag indicating if the service should be restarted if a config
          hot-reload failed.

        Returns:
          True if unchanged, or if changed successfully; False otherwise
        """
        # Cannot use a period ('.') as a separator because of a mongo/juju issue:
        # https://github.com/canonical/operator/issues/585
        unflattened_config = unflatten(dict(self.model.config), "::")

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
        config_hash = utils.sha256(config_yaml)

        logger.debug(
            "recevier: %s - %s",
            receiver["name"],
            "changed" if config_hash != self._stored.config_hash else "no change",
        )

        if config_hash != self._stored.config_hash:
            self.container.push(self._config_path, config_yaml)

            # Send an HTTP POST to alertmanager to hot-reload the config.
            # This reduces down-time compared to restarting the service.
            if self.api_client.reload():
                self._stored.config_hash = config_hash
                success = True
            else:
                logger.warning("config reload via HTTP POST failed")
                if restart_on_failure:
                    if self._restart_service():
                        self._stored.config_hash = config_hash
                        success = True
                    else:
                        success = False
                else:
                    # reload failed but not restarting
                    success = False
        else:
            # no change in config
            success = True

        # update amtool config file
        amtool_config = yaml.safe_dump(
            {"alertmanager.url": "http://localhost:{}".format(self.api_port)}
        )
        self.container.push(self._amtool_config_path, amtool_config, make_dirs=True)

        return success

    @property
    def api_address(self):
        return "http://{}:{}".format(self.private_address, self.api_port)

    @property
    def api_client(self) -> AlertmanagerAPIClient:
        """:obj:`AlertmanagerAPIClient`: an API client instance for communicating with the alertmanager workload
        server"""
        return AlertmanagerAPIClient(self.private_address, self._api_port)

    def _patch_k8s_service(self):
        """Fix the Kubernetes service that was setup by Juju with correct port numbers"""
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
        if not self._stored.pebble_ready:
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return False

        # Wait for IP address. IP address is needed for config hot-reload and status updates.
        if not self.private_address:
            self.unit.status = MaintenanceStatus("Waiting for IP address")
            return False

        # In the case of a single unit deployment, no 'RelationJoined' event is emitted, so
        # setting IP here.
        self._store_private_address()
        self.provider.update_relation_data()
        self.karma_lib.target = self.api_address

        # Update pebble layer
        try:
            layer_changed = self._update_layer(restart=False)
            if layer_changed and (
                not self.is_service_running
                or (self.num_peers > 0 and not self._stored.launched_with_peers)
            ):
                self._restart_service()

            # Update config file
            if not self._update_config(restart_on_failure=True):
                self.unit.status = BlockedStatus("Config update failed")
                return False

        except ChangeError as e:
            logger.error("Pebble error: %s", str(e))
            self.unit.status = BlockedStatus("Pebble error")
            return False

        self.provider.ready()
        self.unit.status = ActiveStatus()

        return True

    def _on_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        self._stored.pebble_ready = True
        self._common_exit_hook()

    def _on_config_changed(self, event: ops.charm.ConfigChangedEvent):
        self._common_exit_hook()

    def _on_start(self, event: ops.charm.StartEvent):
        # With Juju 2.9.5 encountered a scenario in which pebble_ready and config_changed fired, but IP address was not
        # available and the status was stuck on "Waiting for IP address". Adding this hook as a workaround.
        self._common_exit_hook()

    def _on_install(self, _):
        """Event handler for the install event during which we will update the K8s service"""
        self._patch_k8s_service()

    def _on_peer_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        self._common_exit_hook()

    def _on_peer_relation_changed(self, event: ops.charm.RelationChangedEvent):
        # `relation_changed` is needed in addition to `relation_joined` because when a second unit
        # joins, the first unit must be restarted and provided with the second unit's IP address.
        # when the first unit sees "joined", it is not guaranteed that the second unit already has
        # an IP address.
        self._common_exit_hook()

    def _on_peer_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        # No need to update peers - the cluster updates itself internally when a unit is not available.
        # No need to update consumer relations because consumers will get a relation changed event, and
        # addresses are pulled from unit data bags by the consumer library.
        pass

    def _on_update_status(self, event: ops.charm.UpdateStatusEvent):
        if status := self.api_client.status():
            logger.info(
                "alertmanager %s is up and running (uptime: %s); "
                "cluster mode: %s, with %d peers",
                status["versionInfo"]["version"],
                status["uptime"],
                status["cluster"]["status"],
                len(status["cluster"]["peers"]),
            )

        # Calling the common hook to make sure a single unit set its IP in case all events fired
        # before an IP address was ready, leaving UpdateStatue as the last resort.
        self._common_exit_hook()

    def _on_upgrade_charm(self, _):
        # Ensure that older deployments of Alertmanager run the logic
        # to patch the K8s service
        self._patch_k8s_service()

        # update config hash. pebble may not be ready so using try-except
        try:
            self._stored.config_hash = utils.sha256(
                yaml.safe_dump(yaml.safe_load(self.container.pull(self._config_path)))
            )
        except (ops.pebble.ConnectionError, urllib.error.URLError, FileNotFoundError):
            self._stored.config_hash = ""

        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same as before
        # Calling the common hook to update IP address to the new one
        self._common_exit_hook()

    def _get_unit_address_map(self) -> Dict[ops.model.Unit, Optional[str]]:
        """Create a mapping between Unit and its IP address.

        The returned addresses do not include ports nor scheme.
        If an IP address is not available, the corresponding value will be None.
        """
        # For some reason self.peer_relation.units returns an empty set so using `isinstance`
        addresses = {
            unit: data.get("private_address")
            for unit, data in self.peer_relation.data.items()
            if isinstance(unit, ops.model.Unit)
        }
        return addresses

    def _get_peer_addresses(self) -> List[str]:
        """Create a list of HA addresses of all peer units (all units excluding current).

        The returned addresses include the HA port number but do not include scheme (http).
        If a unit does not have an API, it will be omitted from the list.
        """
        return [
            "{}:{}".format(address, self._ha_port)
            for unit, address in self._get_unit_address_map().items()
            if unit is not self.unit and address is not None
        ]


if __name__ == "__main__":
    main(AlertmanagerCharm, use_juju_for_storage=True)

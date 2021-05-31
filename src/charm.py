#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from provider import AlertmanagerProvider
from utils import append_unless, md5, fetch_url

import ops
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.framework import StoredState

from typing import List, Dict, Union, Optional
import urllib.parse
import json
import requests
import logging

logger = logging.getLogger(__name__)

CONFIG_CONTENT = """
route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 3h
  receiver: default_pagerduty
inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['cluster', 'service']
receivers:
  - name: default_pagerduty
    pagerduty_configs:
     - send_resolved:  true
       service_key: '{pagerduty_key}'
"""

# path, inside the workload container, to the alertmanager configuration file
CONFIG_PATH = "/etc/alertmanager/alertmanager.yml"

# path, inside the workload container for alertmanager logs, e.g. 'nflogs', 'silences'.
STORAGE_PATH = "/alertmanager"

# String literals for this charm (must match metadata.yaml)
PEER = "replicas"  # for HA relation
SERVICE = "alertmanager"  # chosen arbitrarily to match charm name
CONTAINER = "alertmanager"  # automatically determined from charm name
LAYER = "alertmanager"  # layer label argument for container.add_layer


class AlertmanagerHTTPController:
    pass


class AlertmanagerCharm(CharmBase):
    """A Juju charm for Alertmanager"""

    API_PORT: str = "9093"  # port to listen on for the web interface and API
    HA_PORT: str = "9094"  # port for HA-communication between multiple instances of alertmanger

    _stored = StoredState()

    @property
    def unit_id(self):
        return int(self.unit.name.split('/')[1])

    def is_service_active(self, service_name: str) -> bool:
        container = self.unit.get_container(CONTAINER)
        return container.get_service(service_name).is_running()

    def restart_service(self, service_name: str):
        container = self.unit.get_container(CONTAINER)

        logger.info("Restarting service %s", service_name)

        try:
            # if the service does not exist, ModelError will be raised
            if self.is_service_active(service_name):
                container.stop(service_name)
            container.start(service_name)

        except ops.model.ModelError:
            logger.warning("Service does not (yet?) exist; (re)start aborted")
        except Exception as e:
            logger.warning("failed to (re)start service: %s", str(e))
            raise

        # Update "launched with peers" flag.
        # The service will be restarted when peers joined if this is False.
        container = self.unit.get_container(CONTAINER)
        plan = container.get_plan()
        service = plan.services.get(SERVICE)
        self._stored.launched_with_peers = "yes" if "--cluster.peer" in service.command else None

    @property
    def private_address(self) -> Optional[str]:
        """
        Get the unit's ip address.
        This is a temporary placeholder for this functionality, as it should be integrated in ops.

        :return: None if called before unit "joined"; unit's ip address otherwise
        """

        relation = self.model.get_relation(PEER)
        bind_address = self.model.get_binding(relation).network.bind_address
        # bind_address = check_output(["unit-get", "private-address"]).decode().strip()

        return None if bind_address is None else str(bind_address)

    @property
    def peer_relation(self):
        return self.model.get_relation(PEER)

    def __init__(self, *args):
        logger.info("Initializing charm.")
        super().__init__(*args)
        self.framework.observe(self.on.alertmanager_pebble_ready,
                               self._on_alertmanager_pebble_ready)
        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)

        self.framework.observe(self.on.start,
                               self._on_start)

        self.framework.observe(self.on.update_status,
                               self._on_update_status)

        self.framework.observe(self.on[PEER].relation_departed,
                               self._on_replicas_relation_departed)
        self.framework.observe(self.on[PEER].relation_changed,
                               self._on_replicas_relation_changed)
        self.framework.observe(self.on[PEER].relation_joined,
                               self._on_replicas_relation_joined)

        # link LeaderElected to RelationChanged because in case a departing unit is the leader, it
        # is not guaranteed that LeaderElected would be emitted before RelationChanged, and
        # therefore the "is_leader" guards would prevent key operator logic from being executed.
        self.framework.observe(self.on.leader_elected,
                               # self._on_replicas_relation_changed)
                               self._on_leader_elected)

        self.provider = AlertmanagerProvider(self, SERVICE)

        self._stored.set_default(
            config_hash=None,
            pebble_ready=None,
            started=None,
            launched_with_peers=None,
            config_valid=None,
        )

    def _on_start(self, event: ops.charm.StartEvent):
        logger.info("START")
        if not all([self.private_address, self._stored.pebble_ready]):
            logger.info("on_start: deferring because no private address or not pebble_ready")
            event.defer()
            self.update_unit_status()
            return

        # TODO make _store_private_address an inner function?
        self._store_private_address()
        # self.update_config()
        self.update_layer()

        logger.info("on_start: setting _stored.started = 'yes'")
        self._stored.started = "yes"

        self.update_unit_status()

        if not self._stored.config_valid:
            logger.info("StartEvent emitted before ConfigChangedEvent. "
                        "This may prevent startup sequence from completing until "
                        "ConfigChangedEvent is re-emitted, e.g. on the next UpdateStatusEvent.")

        if self.unit.is_leader():
            self.app.status = ActiveStatus()

    def update_unit_status(self):
        if self._stored.started and self._stored.config_valid:
            # All is well, set an ActiveStatus
            # self.provider.ready()
            self.unit.status = ActiveStatus()
        else:
            # self.provider.unready()
            if self._stored.started:
                self.unit.status = BlockedStatus("PagerDuty service key missing")
            elif self._stored.config_valid:
                self.unit.status = WaitingStatus("Waiting for IP address")
            else:  # neither "started" or "config_valid"
                self.unit.status = WaitingStatus("Waiting for unit to start")

    def _on_update_status(self, event: ops.charm.UpdateStatusEvent):
        logger.info("UPDATE STATUS")
        # TODO use api address only if it is not None, and remove the try below
        # TODO store private address regardless, to simplify

        if not self.private_address:
            logger.info("Skipping UpdateStatusEvent because ip address is not available")
            return

        status_url = urllib.parse.urljoin(f"http://{self.get_api_address()}", "/api/v2/status")
        status = fetch_url(status_url)
        if not status:
            logger.warning("alertmanager is down (determined by trying to fetch %s)", status_url)

            # After a host reboot, bind_address returns the old ip address from before the reboot
            # so update_status is the (only) opportunity to fix it.
            # Need to update IPs and layer before restarting.
            if self.get_stored_unit_address() != self.private_address:
                self._store_private_address()

            self.update_config()
            self.update_layer()
            self.update_relations()
            self.restart_service(SERVICE)
        else:
            status = json.loads(status)

            logger.info("alertmanager %s is up and running (uptime: %s); "
                        "cluster mode: %s, with %d peers",
                        status["versionInfo"]["version"],
                        status["uptime"],
                        status["cluster"]["status"],
                        len(status["cluster"]["peers"]))

        # TODO: fetch prometheus status (<prom_ip>:9090/api/v1/alertmanagers) and confirm that
        #  data.activeAlertmanagers count and IPs match ours

    def _on_alertmanager_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        logger.info("PEBBLE READY")
        self._stored.pebble_ready = "yes"

        if not self._stored.config_valid or not self._stored.started:
            logger.info("PebbleReady emitted before StartEvent or ConfigChangedEvent. "
                        "This may prevent startup sequence from completing until re-emission is "
                        "triggered, e.g. on the next UpdateStatusEvent.")

    def _unit_bucket(self, key: str) -> Optional[str]:
        return self.peer_relation.data[self.unit].get(key)

    def _store_private_address(self):
        """
        Precondition: IP address is available
        """
        bind_address: Optional[str] = self.private_address
        if not bind_address:
            logger.warning("bind_address is None")
        # update only if changed
        # TODO does writing the same value generate a relation-changed event?
        if self.peer_relation.data[self.unit].get('private-address') != bind_address:
            logger.info("changing private address from %s to %s",
                        self.peer_relation.data[self.unit].get('private-address'), bind_address)
            self.peer_relation.data[self.unit]['private-address'] = bind_address

        return True

    def _alertmanager_layer(self) -> dict:
        """Returns Pebble configuration layer for alertmanager"""
        return {
            "summary": "alertmanager layer",
            "description": "pebble config layer for alertmanager",
            "services": {
                SERVICE: {
                    "override": "replace",
                    "summary": "alertmanager service",
                    "command": self._command(),
                    "startup": "enabled",
                    # "environment": {"thing": self.model.config["thing"]},
                }
            },
        }

    def update_relations(self):
        logger.info("update_relations: stored api addresses: %s", self.get_api_addresses())
        if self.unit.is_leader():
            self.provider.update_alerting()

    def _on_replicas_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        logger.info("REPLICAS RELATION JOINED (self: %s, remote: %s)",
                    self.unit.name.split('/')[1], event.unit.name.split('/')[1])

    def _on_leader_elected(self, event: ops.charm.LeaderElectedEvent):
        logger.info("LEADER ELECTED")

        self.update_layer(restart=not bool(self._stored.launched_with_peers))
        self.update_relations()

    def _on_replicas_relation_changed(self, event: ops.charm.RelationChangedEvent):
        logger.info("REPLICAS RELATION CHANGED (self: %s, remote: %s)",
                    self.unit.name.split('/')[1], event.unit.name.split('/')[1])
        if not self._stored.started:
            event.defer()
            return

        self.update_layer(restart=not bool(self._stored.launched_with_peers))
        self.update_relations()

    def _on_replicas_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        logger.info("REPLICAS RELATIONS DEPARTED")
        if not self._stored.started:
            event.defer()
            return

        self.update_layer(restart=False)
        self.update_relations()

    def is_config_valid(self) -> bool:
        return bool(self.model.config.get("pagerduty_key"))

    def _on_config_changed(self, event: ops.charm.ConfigChangedEvent):
        logger.info("CONFIG CHANGED")
        if not self._stored.started:
            event.defer()
            self.update_unit_status()
            return

        # TODO rename from config_valid to config_pushed and move under `update_config`
        self._stored.config_valid = "yes" if self.is_config_valid() else None

        # consider restarting the service only if ip was already assigned, i.e.
        # do not restart if this event is part of the startup sequence.
        # restart_on_failure = self.get_stored_unit_address() is not None
        self.update_config(restart_on_failure=True)

        self.update_unit_status()

    def _render_config_file(self):
        """Create the alertmanager config file from self.model.config"""
        return CONFIG_CONTENT.format(pagerduty_key=self.model.config["pagerduty_key"])

    def get_peer_addresses(self) -> List[Union[str, None]]:
        unit_addresses = self.get_unit_addresses()
        unit_addresses.pop(self.unit)
        peer_ha_addresses = [append_unless(None,
                                           address,
                                           f":{self.HA_PORT}")
                             for address in unit_addresses.values()]

        return peer_ha_addresses

    def get_stored_unit_address(self) -> Optional[str]:
        return self._unit_bucket('private-address')

    def get_unit_addresses(self) -> Dict[ops.model.Unit, Union[str, None]]:
        """
        Get the _stored_ unit addresses.
        :return: a map from unit to bind address, no port numbers (None if not available yet)
        """
        relation = self.peer_relation

        return {unit: relation.data[unit].get('private-address', None) for unit in relation.units}

    def get_api_address(self) -> Optional[str]:
        unit_address = self.get_unit_addresses()[self.unit]  # TODO make this less ugly
        return append_unless(None, unit_address, f":{self.API_PORT}")

    def get_api_addresses(self) -> List[Union[str, None]]:
        """
        :return: a list of all units' addresses, including the API port (None if not available yet)
        """
        logger.info("get_api_addresses: all addresses: %s", self.get_unit_addresses())
        return [append_unless(None,
                              address,
                              f":{self.API_PORT}")
                for address in self.get_unit_addresses().values()]

    def _command(self):
        """
        :return: full command line to start alertmanager
        """
        peer_addresses = [address for address in self.get_peer_addresses() if address is not None]

        # cluster listen address - empty string disables HA mode
        listen_address_arg = "" if len(peer_addresses) == 0 else f"0.0.0.0:{self.HA_PORT}"

        # The chosen port in the cluster.listen-address flag is the port that needs to be specified
        # in the cluster.peer flag of the other peers.
        # Assuming all replicas use the same port.
        # Sorting for repeatability in comparing between service layers.
        peer_cmd_args = ' '.join(sorted([f"--cluster.peer={address}"
                                         for address in peer_addresses]))

        return "/bin/alertmanager --config.file={} --storage.path={} --web.listen-address=:{} " \
               "--cluster.listen-address={} {}".format(
                   CONFIG_PATH,
                   STORAGE_PATH,
                   self.API_PORT,
                   listen_address_arg,
                   peer_cmd_args)

    def update_layer(self, restart: bool = True) -> bool:
        """
        Update service layer to reflect changes in peers (replicas).
        :return: True if anything changed; False otherwise
        """

        # _store_private_address is here because of the "disappearing data buckets" phenomenon:
        # [deploy 4 units -> add relation to prometheus -> config pager duty] - after config
        # changed event, various unit buckets disappear one after the other, and as a result the ip
        # addresses shows up as None.
        self._store_private_address()

        overlay = self._alertmanager_layer()

        container = self.unit.get_container(CONTAINER)
        plan = container.get_plan()

        is_changed = False
        # if this unit has just started, the services does not yet exist - using "get"
        service = plan.services.get(SERVICE)
        if service is None or service.command != overlay["services"][SERVICE]["command"]:
            is_changed = True
            container.add_layer(LAYER, overlay, combine=True)

        if is_changed and restart:
            self.restart_service(SERVICE)

        return is_changed

    def _reload_config(self) -> bool:
        """
        Send an HTTP POST to alertmanager to reload the config.
        This reduces down-time compared to restarting the service.
        """
        if api_address := self.get_api_address():
            url = urllib.parse.urljoin(f"http://{api_address}", "/-/reload")
            try:
                response = requests.post(url)
                logger.info("config reload via %s: %d %s",
                            url, response.status_code, response.reason)
                return response.status_code == 200 and response.reason == 'OK'
            except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
                logger.error("config reload error via %s: %s", url, str(e))
                return False
        else:
            logger.error("config reload error: no ip address")
            return False

    def update_config(self, restart_on_failure: bool = False) -> Optional[bool]:
        """
        :return: None if failed, True if anything changed, False otherwise
        """
        if not self.is_config_valid():
            logger.warning("Config is incomplete/invalid; skipping config update")
            return None

        config_file = self._render_config_file()
        config_hash = md5(config_file)
        is_changed = False
        if config_hash != self._stored.config_hash:
            is_changed = True
            # Get a reference to the container so we can manipulate it
            container = self.unit.get_container(CONTAINER)
            container.push(CONFIG_PATH, config_file)
            self._stored.config_hash = config_hash
            logger.info("new config hash: %s", config_hash)

        if is_changed:
            if not self._reload_config():
                logger.warning("config reload via HTTP POST failed")
                if restart_on_failure:
                    self.restart_service(SERVICE)

        return is_changed


if __name__ == "__main__":
    main(AlertmanagerCharm)

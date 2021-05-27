#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
from subprocess import check_output

from provider import AlertingProvider
from utils import append_unless, md5, fetch_url

import ops
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
from ops.framework import StoredState

from typing import List, Dict, Union, Optional, Type
import functools
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


class DeferEventError(Exception):
    pass


def defer_on(*exception_class: Type[Exception]):
    def annotation(func):
        @functools.wraps(func)
        def wrapped(self, event: ops.charm.EventBase, *args, **kwargs):
            try:
                func(self, event, *args, **kwargs)
            except exception_class as e:
                self.unit.status = BlockedStatus(str(e))
                event.defer()
        return wrapped
    return annotation


class ExtendedCharmBase(CharmBase):
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

    @property
    def private_address(self) -> Optional[str]:
        """
        Get the unit's ip address.
        This is a temporary place for this functionality, as it should be integrated in ops.

        FIXME Currently, both get_relation() and unit-get may return None / empty string when
              called from on_pebble_ready. This can be reproduced by adding ~3 units.
              This seems like a bug, so the easiest workaround is to crash and let juju restart,
              at which point an ip should be available.
              Without being able to get an ip address reliably on unit startup, the only other
              thing to rely on is the update_status event, whose frequency is configurable.
        :return:
        """
        relation = self.model.get_relation(PEER)
        bind_address = self.model.get_binding(relation).network.bind_address
        logger.info("in private address: relation = %s, address = %s (%s)", relation, bind_address, str(bind_address))
        # logger.info("all interfaces: %s",
        #             [(interface.name, interface.address) for interface in
        #              self.model.get_binding(relation).network.interfaces])
        return None if bind_address is None else str(bind_address)

        # bind_address = check_output(["unit-get", "private-address"]).decode().strip()

        # if ip address is not yet available, raises AddressValueError('Address cannot be empty'),
        # which is intentionally left to crash the unit, such that by next startup the ip address
        # would already be available.
        # return IPv4Address(bind_address)


class AlertmanagerCharm(ExtendedCharmBase):
    """A Juju charm for Alertmanager"""

    API_PORT: str = "9093"  # port to listen on for the web interface and API
    HA_PORT: str = "9094"  # port for HA-communication between multiple instances of alertmanger

    _stored = StoredState()

    def __init__(self, *args):
        logger.debug("Initializing charm.")
        super().__init__(*args)
        self.framework.observe(self.on.alertmanager_pebble_ready,
                               self._on_alertmanager_pebble_ready)
        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)

        self.framework.observe(self.on.update_status,
                               self._on_update_status)

        self.framework.observe(self.on[PEER].relation_departed,
                               self._on_replicas_relation_departed)
        # self.framework.observe(self.on[PEER].relation_joined,
        #                        self._on_replicas_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed,
                               self._on_replicas_relation_changed)

        self.provider = AlertingProvider(self, "alerting", SERVICE)

        self._stored.set_default(config_hash=None)

    def _on_update_status(self, event: ops.charm.UpdateStatusEvent):
        # TODO use api address only if it is not None, and remove the try below
        # TODO store private address regardless, to simplify
        status_url = urllib.parse.urljoin(f"http://{self.get_api_address()}", "/api/v2/status")
        status = fetch_url(status_url)
        if not status:
            logger.warning("alertmanager is down (determined by trying to fetch %s)", status_url)

            # After a host reboot, bind_address returns the old ip address from before the reboot
            # so update_status is the (only) opportunity to fix it.
            # Need to update IPs and layer before restarting.
            if self.get_stored_unit_address() != self.private_address:
                try:
                    self._store_private_address()
                except DeferEventError:
                    # skip this update_status if an ip address is still unavailable
                    return
            self._update_replicas()
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

    @defer_on(DeferEventError)
    def _on_alertmanager_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.
        """
        logger.debug("pebble ready: setting ip address in unit relation bucket")
        self._store_private_address()
        self.update_layer(restart=True)
        self.update_config(restart_on_failure=True)

        # TODO for some reason, upgrade-charm does not trigger alerting_relation_changed when a new
        #  ip address is written to the relation data, so calling it manually here
        # if self.unit.is_leader():
        #     self.provider.update_alerting()

        # All is well, set an ActiveStatus
        self.provider.ready()
        self.unit.status = ActiveStatus()

        if self.unit.is_leader():
            self.app.status = ActiveStatus()

    def _unit_bucket(self, key: str) -> Optional[str]:
        relation = self.model.get_relation(PEER)
        return relation.data[self.unit].get(key)

    def _store_private_address(self):
        bind_address: Optional[str] = self.private_address
        if bind_address is None:
            logger.warning("IP address not yet available")
            raise DeferEventError("IP address not available")

        logger.info("bind_address: %s = %s", type(bind_address), bind_address)
        # if bind_address is None:
        #     # This can happen, even when called from pebble_ready
        #     raise DeferEventError("IP address not ready")

        # TODO update only if changed (does writing the same value generate a relation-changed event?)
        relation = self.model.get_relation(PEER)
        relation.data[self.unit]['private-address'] = bind_address
        logger.info("private address (%s): %s; unit bucket: %s", self.unit.name, bind_address, relation.data[self.unit])

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

    # @status_catcher
    # def _on_replicas_relation_joined(self, event: ops.charm.RelationJoinedEvent):
    #     logger.debug("relation changed meta={} model={} unit={}".format(self.meta.name, self.model.name, self.unit_id))
    #
    #     self.update_layer(restart=True)

    def _update_replicas(self):
        self.update_config()

        if self.unit.is_leader():
            self.provider.update_alerting()  # TODO only if "private-address" present?

        # restart only if called after ip address is assigned (after pebble_ready)
        # restart = self._unit_bucket("private-address") is not None
        # logger.debug("_on_replicas_relation_changed: unit_bucket: %s, restart = %s", self._unit_bucket(), restart)
        self.update_layer()  # TODO remove this when canonical/operator/issues/542 is resolved?

    @defer_on(DeferEventError)
    def _on_replicas_relation_changed(self, event: ops.charm.RelationChangedEvent):
        unit_num = self.unit.name.split('/')[1]
        logger.debug("relation changed meta={} model={} unit={}".format(self.meta.name, self.model.name, unit_num))
        self._update_replicas()

    @defer_on(DeferEventError)
    def _on_replicas_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        logger.info('departed event relation unit bucket: %s -> %s', event.relation.data, event.relation.data[self.unit])
        self._update_replicas()

    @defer_on(DeferEventError)
    def _on_config_changed(self, event: ops.charm.ConfigChangedEvent):
        logger.debug('_on_config_changed: self._unit_bucket("private-address") = %s (%s)', self._unit_bucket("private-address"), type(self._unit_bucket("private-address")))

        # consider restarting the service only if ip was already assigned, i.e.
        # do not restart if this event is part of the startup sequence.
        restart_on_failure = self.get_stored_unit_address() is not None
        self.update_config(restart_on_failure)

    def _config_file(self):
        """Create the alertmanager config file from self.model.config"""
        if not self.model.config["pagerduty_key"]:
            raise DeferEventError("Missing pagerduty_key config value")

        return CONFIG_CONTENT.format(pagerduty_key=self.model.config["pagerduty_key"])

    def get_peer_addresses(self) -> List[Union[str, None]]:
        unit_addresses = self.get_unit_addresses()
        # logger.debug("before pop: %s", unit_addresses)
        self_address = unit_addresses.pop(self.unit)
        # logger.debug("after pop: %s", unit_addresses)
        peer_ha_addresses = [append_unless(None,
                                           address,
                                           f":{self.HA_PORT}")
                             for address in unit_addresses.values()]

        logger.debug("current unit: %s (%s); peer addresses: %s (taken from %s)", self.unit_id, self_address, peer_ha_addresses, self.get_unit_addresses())
        return peer_ha_addresses

    def get_stored_unit_address(self) -> Optional[str]:
        # TODO rename to cached?
        return self._unit_bucket('private-address')

    def get_unit_addresses(self) -> Dict[ops.model.Unit, Union[str, None]]:
        """
        Get the _stored_ unit addresses.
        :return: a map from unit to bind address, no port numbers (None if not available yet)
        """
        relation = self.model.get_relation(PEER)

        all_objects = {obj: relation.data[obj] for obj in relation.data}
        logger.debug("stored unit address: all objs: %s", all_objects)

        return {unit: relation.data[unit].get('private-address', None) for unit in relation.data
                if isinstance(unit, ops.model.Unit)}

    def get_api_address(self) -> Optional[str]:
        unit_address = self.get_unit_addresses()[self.unit]  # TODO make this less ugly
        return append_unless(None, unit_address, f":{self.API_PORT}")

    def get_api_addresses(self) -> List[Union[str, None]]:
        """
        :return: a list of all units' addresses, including the API port (or None if not available yet)
        """
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
        overlay = self._alertmanager_layer()

        container = self.unit.get_container(CONTAINER)
        plan = container.get_plan()

        is_changed = False
        # if this unit has just started, the services does not yet exist - using "get"
        service = plan.services.get(SERVICE)
        logger.debug("service = %s", service)
        if service is None or service.command != overlay["services"][SERVICE]["command"]:
            is_changed = True
            logger.debug("overlay cmd: %s", overlay["services"][SERVICE]["command"])
            container.add_layer(LAYER, overlay, combine=True)

        if is_changed and restart:
            self.restart_service(SERVICE)

        return is_changed

    def reload_config(self) -> bool:
        """
        Send an HTTP POST to alertmanager to reload the config.
        This reduces down-time compared to restarting the service.
        """
        if api_address := self.get_api_address():
            url = urllib.parse.urljoin(f"http://{api_address}", "/-/reload")
            try:
                response = requests.post(url)
                logger.info("config reload via %s: %d %s", url, response.status_code, response.reason)
                return response.status_code == 200 and response.reason == 'OK'
            except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
                logger.info("config reload error via %s: %s", url, str(e))
                return False
        else:
            logger.info("config reload error: no ip address")
            return False

    def update_config(self, restart_on_failure: bool = False) -> bool:
        """
        :return: True if anything changed; False otherwise
        """
        # TODO validate config
        config_file = self._config_file()
        config_hash = md5(config_file)
        is_changed = False
        if config_hash != self._stored.config_hash:
            is_changed = True
            # Get a reference to the container so we can manipulate it
            container = self.unit.get_container(CONTAINER)
            container.push(CONFIG_PATH, config_file)
            self._stored.config_hash = config_hash
            logger.debug("new config hash: %s", config_hash)

        if is_changed:
            if not self.reload_config():
                logger.warning("config reload via HTTP POST failed")
                if restart_on_failure:
                    self.restart_service(SERVICE)

        return is_changed


if __name__ == "__main__":
    main(AlertmanagerCharm)

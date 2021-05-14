#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from provider import AlertingProvider

import ops
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
from ops.framework import StoredState

from typing import List
import hashlib
import functools
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

HA_PORT = "9094"

# path, inside the workload container, to the alertmanager configuration file
CONFIG_PATH = "/etc/alertmanager/alertmanager.yml"

# path, inside the workload container for alertmanager logs, e.g. 'nflogs', 'silences'.
STORAGE_PATH = "/alertmanager"


def restart_service(container: ops.model.Container, service: str):
    logger.info("Restarting service %s", service)

    # if the service does not exist, it will raise a ModelError
    if container.get_service(service).is_running():
        container.stop(service)
    container.start(service)


class DeferEventError(Exception):
    pass


def status_catcher(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
        except DeferEventError as e:
            self.unit.status = BlockedStatus(str(e))

    return wrapped


def leader_only(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        if not self.unit.is_leader():
            return
        func(*args, **kwargs)

    return wrapped


def _hash(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values"""
    if isinstance(hashable, str):
        hashable = hashable.encode('utf-8')
    return hashlib.md5(hashable).hexdigest()


class AlertmanagerCharm(CharmBase):
    """A Juju charm for Alertmanager"""

    _stored = StoredState()

    def __init__(self, *args):
        logger.debug("Initializing charm.")
        super().__init__(*args)
        self.framework.observe(self.on.alertmanager_pebble_ready,
                               self._on_alertmanager_pebble_ready)
        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)

        self.framework.observe(self.on["replicas"].relation_joined,
                               self._on_replicas_relation_joined)
        self.framework.observe(self.on["replicas"].relation_changed,
                               self._on_replicas_relation_changed)
        self.framework.observe(self.on["replicas"].relation_departed,
                               self._on_replicas_relation_departed)

        self.provider = AlertingProvider(self, "alerting", "alertmanager")

        self._stored.set_default(config_hash=None)

    def _on_alertmanager_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.
        """
        logger.debug("pebble ready")
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        plan = container.get_plan()

        # If this is the first unit to start up, then pebble_ready fires before any service is
        # running, so need to add and start the initial layer.
        # Otherwise (when this is not the first unit), a service layer was already added and
        # (re)started.
        if "alertmanager" not in plan.services:
            container.add_layer("alertmanager", self._alertmanager_layer(), combine=True)
            # Autostart any services that were defined with startup: enabled
            container.autostart()

    def _configure(self, event):
        self.update_config_file()

        # All is well, set an ActiveStatus
        self.provider.ready()
        self.unit.status = ActiveStatus()

    def _alertmanager_layer(self) -> dict:
        """Returns Pebble configuration layer for alertmanager"""
        return {
            "summary": "alertmanager layer",
            "description": "pebble config layer for alertmanager",
            "services": {
                "alertmanager": {
                    "override": "replace",
                    "summary": "alertmanager service",
                    "command": "/bin/alertmanager --config.file={} --storage.path={}".format(
                        CONFIG_PATH, STORAGE_PATH),
                    "startup": "enabled",
                    # "environment": {"thing": self.model.config["thing"]},
                }
            },
        }

    @status_catcher
    def _on_replicas_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        logger.debug("relation joined meta={} model={}".format(self.meta.name, self.model.name))
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

        if any([self.update_replicas()]):
            container = self.unit.get_container("alertmanager")
            restart_service(container, "alertmanager")

    @status_catcher
    def _on_replicas_relation_changed(self, event: ops.charm.RelationChangedEvent):
        unit_num = self.unit.name.split('/')[1]
        logger.debug("relation changed meta={} model={} unit={}".format(self.meta.name, self.model.name, unit_num))
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

        # TODO when the bug is fixed and "relation_changed" is fired together with "departed",
        #      use this code here instead of duplicating in "joined" and "departed".
        # if any([self.update_replicas()]):
        #     container = self.unit.get_container("alertmanager")
        #     restart_service(container, "alertmanager")

    @status_catcher
    def _on_replicas_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

        if any([self.update_replicas()]):
            container = self.unit.get_container("alertmanager")
            restart_service(container, "alertmanager")

    @status_catcher
    def _on_config_changed(self, event: ops.charm.ConfigChangedEvent):
        # TODO validate config
        self._configure(event)
        for relation in self.model.relations["alerting"]:
            self.provider.update_alerting(relation)

    def _config_file(self):
        """Create the alertmanager config file from self.model.config"""
        if not self.model.config["pagerduty_key"]:
            raise DeferEventError("Missing pagerduty_key config value")

        return CONFIG_CONTENT.format(pagerduty_key=self.model.config["pagerduty_key"])

    def num_units(self):
        """
        :return: number of units (replicas, including self) at play
        """
        # The relation does not list ourself as a unit so we must add 1
        return 1 + self.num_peers()

    def num_peers(self):
        """
        :return: number of peers (replicas, excluding self) at play
        """
        relation = self.model.get_relation("replicas")
        return 0 if relation is None else len(relation.units)

    def get_peer_addresses(self) -> List[str]:
        # extract this unit_id from unit name string, e.g. "alertmanager/0"
        unit_id = int(self.unit.name.split('/')[1])
        logger.debug("curr unit id: %s", unit_id)
        # assuming unit ids are always 0..num_units-1
        peer_ids = set(range(self.num_units())).difference([unit_id])
        logger.debug("peer unit ids: %s", peer_ids)

        return [self.unit_address(peer_id) for peer_id in peer_ids]

    def unit_address(self, unit_id: int):
        # unit address is comprised of meta name ("alertmanager"), unit id, and the juju model name
        template = "{charm.meta.name}-{unit_id}.{charm.meta.name}-endpoints.{charm.model.name}.svc.cluster.local"
        return template.format(charm=self, unit_id=unit_id)

    def update_replicas(self) -> bool:
        """
        :return: True if container restart is required; False otherwise
        """
        peer_addresses: List[str] = self.get_peer_addresses()

        # cluster listen address - empty string disables HA mode
        listen_address_arg = "" if len(peer_addresses) == 0 else f"0.0.0.0:{HA_PORT}"

        # The chosen port in the cluster.listen-address flag is the port that needs to be specified
        # in the cluster.peer flag of the other peers.
        # Assuming all replicas use the same port.
        # Sorting for repeatability in comparing between service layers.
        peer_cmd_args = ' '.join(sorted(['--cluster.peer={peer_address}:{peer_port}'.format(
            peer_address=address,
            peer_port=HA_PORT
        ) for address in peer_addresses]))

        overlay = {"services": {
            "alertmanager": {
                "override": "replace",
                "summary": "alertmanager service",
                "command": "/bin/alertmanager --config.file={} --storage.path={} --cluster.listen-address={} {}".format(
                    CONFIG_PATH, STORAGE_PATH, listen_address_arg, peer_cmd_args),
                "startup": "enabled",
            }
        }}

        container = self.unit.get_container("alertmanager")
        plan = container.get_plan()

        restart_required = False
        # if this unit has just started, the services does not yet exist - using "get"
        if plan.services.get("alertmanager") != overlay["services"]["alertmanager"]:
            restart_required = True
            logger.debug("overlay cmd: %s", overlay["services"]["alertmanager"]["command"])
            container.add_layer("alertmanager", overlay, combine=True)

        return restart_required

    def update_config_file(self) -> bool:
        """
        :return: True if a restart is required; False otherwise
        """
        config_file = self._config_file()
        config_hash = _hash(config_file)
        restart_required = False
        if config_hash != self._stored.config_hash:
            restart_required = True
            # Get a reference to the container so we can manipulate it
            container = self.unit.get_container("alertmanager")
            container.push(CONFIG_PATH, config_file)
            self._stored.config_hash = config_hash
            logger.debug("new config hash: %s", config_hash)

        return restart_required


if __name__ == "__main__":
    main(AlertmanagerCharm)

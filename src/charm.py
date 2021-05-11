#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import json
import logging

import ops
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
# from ops.framework import StoredState

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
UNIT_ADDRESS = "{}-{}.{}-endpoints.{}.svc.cluster.local"

# path, inside the workload container, to the alertmanager configuration file
CONFIG_PATH = "/etc/alertmanager/alertmanager.yml"

# path, inside the workload container for alertmanager logs, e.g. 'nflogs', 'silences'.
STORAGE_PATH = "/alertmanager"


def restart(container: ops.model.Container, service: str):
    logger.info("Restarting %s", service)
    if container.get_service(service).is_running():
        container.stop(service)
    container.start(service)


class DeferEventError(Exception):
    pass


def status_catcher(func):
    @functools.wraps(func)
    def new_func(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
        except DeferEventError as e:
            self.unit.status = BlockedStatus(str(e))

    return new_func


class AlertmanagerCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        logger.debug("Initializing charm.")
        super().__init__(*args)
        self.framework.observe(self.on.alertmanager_pebble_ready,
                               self._on_alertmanager_pebble_ready)
        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)
        self.framework.observe(self.on["alerting"].relation_changed,
                               self._on_alerting_relation_changed)
        self.framework.observe(self.on["replicas"].relation_changed,
                               self._on_replcas_relation_changed)
        self.framework.observe(self.on["replicas"].relation_departed,
                               self._on_replicas_relation_departed)

    def _on_alertmanager_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.
        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload

        # Add intial Pebble config layer using the Pebble API
        container.add_layer("alertmanager", self._alertmanager_layer(), combine=True)

        # Autostart any services that were defined with startup: enabled
        container.autostart()

    def _configure(self, event):
        """Set Juju / Kubernetes pod spec built from `build_pod_spec()`."""

        if not self.unit.is_leader():
            # TODO is this relevant now? still need to push config?
            logger.debug("Unit is not leader. Cannot set pod spec.")
            self.unit.status = ActiveStatus()
            return

        # Get a reference to the container so we can manipulate it
        container = self.unit.get_container("alertmanager")
        container.push(CONFIG_PATH, self._config_file())

        # All is well, set an ActiveStatus
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
    def _on_alerting_relation_changed(self, event):
        self.update_alerting(event.relation)

    def update_alerting(self, relation):
        if self.unit.is_leader():
            logger.info("Setting relation data: port")
            # if str(self.model.config["port"]) != relation.data[self.app].get("port", None):
            #     relation.data[self.app]["port"] = str(self.model.config["port"])
            relation.data[self.app]["port"] = str(self.model.config["port"])

            logger.info("Setting relation data: addrs")
            addrs = []
            num_units = self.num_units()
            for i in range(num_units):
                addrs.append(
                    UNIT_ADDRESS.format(self.meta.name, i, self.meta.name, self.model.name)
                )
            # if addrs != json.loads(relation.data[self.app].get("addrs", "null")):
            #     relation.data[self.app]["addrs"] = json.dumps(addrs)
            relation.data[self.app]["addrs"] = json.dumps(addrs)

    @status_catcher
    def _on_replcas_relation_changed(self, event):
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.update_alerting(relation)

    @status_catcher
    def _on_replicas_relation_departed(self, event):
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.update_alerting(relation)

    @status_catcher
    def _on_config_changed(self, event: ops.charm.ConfigChangedEvent):
        self._configure(event)
        for relation in self.model.relations["alerting"]:
            self.update_alerting(relation)

    def num_units(self):
        relation = self.model.get_relation("alertmanager")
        # The relation does not list ourself as a unit so we must add 1
        return len(relation.units) + 1 if relation is not None else 1

    def _config_file(self):
        """Create the alertmanager config file from self.model.config"""
        if not self.model.config["pagerduty_key"]:
            raise DeferEventError("Missing pagerduty_key config value")

        return CONFIG_CONTENT.format(pagerduty_key=self.model.config["pagerduty_key"])


if __name__ == "__main__":
    main(AlertmanagerCharm)

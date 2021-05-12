#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from provider import AlertingProvider

import functools
import logging

import ops
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
from ops.framework import StoredState

import hashlib

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

        self.provider = AlertingProvider(self)

        self._stored.set_default(config_hash=None)

    def _on_alertmanager_pebble_ready(self, event: ops.charm.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.
        """
        logger.debug("pebble ready")
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload

        # Add intial Pebble config layer using the Pebble API
        container.add_layer("alertmanager", self._alertmanager_layer(), combine=True)

        # Autostart any services that were defined with startup: enabled
        container.autostart()

    def _configure(self, event):
        """Set Juju / Kubernetes pod spec built from `build_pod_spec()`."""

        config_file = self._config_file()
        config_hash = _hash(config_file)
        if config_hash != self._stored.config_hash:
            # Get a reference to the container so we can manipulate it
            container = self.unit.get_container("alertmanager")
            container.push(CONFIG_PATH, config_file)
            self._stored.config_hash = config_hash
            logger.debug("new config hash: %s", config_hash)

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
        logger.debug("relation joined")

        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

    @status_catcher
    def _on_replicas_relation_changed(self, event: ops.charm.RelationChangedEvent):
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

    @status_catcher
    def _on_replicas_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        if self.unit.is_leader():
            self._configure(event)
            for relation in self.model.relations["alerting"]:
                self.provider.update_alerting(relation)

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


if __name__ == "__main__":
    main(AlertmanagerCharm)

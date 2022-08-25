#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Charm to functionally test the Alertmanager Operator."""

import logging

import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    AlertmanagerRemoteConfigurationConsumer,
)
from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus

logger = logging.getLogger(__name__)


class AlertmanagerTesterCharm(CharmBase):
    """A Charm to functionally test the Alertmanager Operator."""

    ALERTMANAGER_CONFIG_FILE = "/etc/alertmanager/alertmanager.yml"

    def __init__(self, *args):
        super().__init__(*args)
        self.container = self.unit.get_container("remote-configuration-tester")
        self.remote_configuration_consumer = AlertmanagerRemoteConfigurationConsumer(self)

        self.framework.observe(self.on.remote_configuration_tester_pebble_ready, self._on_ready)

    def _on_ready(self, event: PebbleReadyEvent) -> None:
        if not self.container.can_connect():
            self.unit.status = WaitingStatus("Waiting for the container to be ready")
            event.defer()
            return
        self.container.push(
            self.ALERTMANAGER_CONFIG_FILE, yaml.safe_dump(self._alertmanager_config)
        )
        self.unit.status = ActiveStatus()

    @property
    def _alertmanager_config(self) -> dict:
        return {
            "route": {
                "receiver": "test_receiver",
                "group_by": ["alertname"],
                "group_wait": "1234s",
                "group_interval": "4321s",
                "repeat_interval": "1111h",
            },
            "receivers": [{"name": "test_receiver"}],
        }


if __name__ == "__main__":
    main(AlertmanagerTesterCharm)

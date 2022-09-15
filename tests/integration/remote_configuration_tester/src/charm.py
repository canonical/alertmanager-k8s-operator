#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Charm to functionally test the Alertmanager Operator."""

import logging

from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    ConfigReadError,
    RemoteConfigurationProvider,
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

        try:
            self.remote_configuration_consumer = RemoteConfigurationProvider.with_config_file(
                charm=self, config_file=self.ALERTMANAGER_CONFIG_FILE
            )
        except ConfigReadError:
            pass

        self.framework.observe(self.on.remote_configuration_tester_pebble_ready, self._on_ready)

    def _on_ready(self, event: PebbleReadyEvent) -> None:
        if not self.container.can_connect():
            self.unit.status = WaitingStatus("Waiting for the container to be ready")
            event.defer()
            return
        self.container.push(self.ALERTMANAGER_CONFIG_FILE, self.config["config_file"])
        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(AlertmanagerTesterCharm)

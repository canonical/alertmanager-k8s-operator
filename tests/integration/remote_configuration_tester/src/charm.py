#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Charm to functionally test the Alertmanager Operator."""

import logging

from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    ConfigReadError,
    RemoteConfigurationProvider,
    load_config_file,
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

        alertmanager_config = {}
        try:
            alertmanager_config = load_config_file(self.ALERTMANAGER_CONFIG_FILE)
        except ConfigReadError:
            logger.warning("Alertmanager config not available yet.")
        if alertmanager_config:
            self.remote_configuration_consumer = RemoteConfigurationProvider(
                charm=self, alertmanager_config=alertmanager_config
            )

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

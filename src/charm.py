#!/usr/bin/env python3
# Copyright 2020 dylan
# See LICENSE file for licensing details.

import functools
import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus

from charms.alertmanager.v1.alertmanager import send_relation_data

log = logging.getLogger(__name__)
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


class BlockedStatusError(Exception):
    pass


def status_catcher(func):
    @functools.wraps(func)
    def new_func(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
        except BlockedStatusError as e:
            self.unit.status = BlockedStatus(str(e))

    return new_func


class AlertmanagerCharm(CharmBase):
    def __init__(self, *args):
        log.debug("Initializing charm.")
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self.on_config_changed)
        self.framework.observe(
            self.on["alerting"].relation_changed, self.on_alerting_changed
        )
        self.framework.observe(
            self.on["alertmanager"].relation_changed, self.on_alertmanager_changed
        )
        self.framework.observe(
            self.on["alertmanager"].relation_departed, self.on_alertmanager_departed
        )

    @status_catcher
    def on_alerting_changed(self, event):
        self.update_alerting(event.relation)

    def update_alerting(self, relation):
        if self.unit.is_leader():
            log.info("Setting relation data")
            port = str(self.model.config["port"])
            addrs = []
            num_units = self.num_units()
            for i in range(num_units):
                addrs.append(
                    UNIT_ADDRESS.format(
                        self.meta.name, i, self.meta.name, self.model.name
                    )
                )
            send_relation_data(relation, self.app, port, addrs)

    @status_catcher
    def on_alertmanager_changed(self, event):
        if self.unit.is_leader():
            self.configure()
            for relation in self.model.relations["alerting"]:
                self.update_alerting(relation)

    @status_catcher
    def on_alertmanager_departed(self, event):
        if self.unit.is_leader():
            self.configure()
            for relation in self.model.relations["alerting"]:
                self.update_alerting(relation)

    @status_catcher
    def on_config_changed(self, _):
        self.configure()
        for relation in self.model.relations["alerting"]:
            self.update_alerting(relation)

    def configure(self):
        """Set Juju / Kubernetes pod spec built from `build_pod_spec()`."""

        self.framework.breakpoint()

        if not self.unit.is_leader():
            log.debug("Unit is not leader. Cannot set pod spec.")
            self.unit.status = ActiveStatus()
            return

        # setting pod spec and associated logging
        self.unit.status = MaintenanceStatus("Building pod spec.")
        log.debug("Building pod spec.")

        pod_spec = self.build_pod_spec()
        log.debug("Setting pod spec.")
        self.model.pod.set_spec(pod_spec)

        self.unit.status = ActiveStatus()
        log.debug("Pod spec set successfully.")

    def build_config_file(self):
        """Create the alertmanager config file from self.model.config"""
        if not self.model.config["pagerduty_key"]:
            raise BlockedStatusError("Missing pagerduty_key config value")

        return CONFIG_CONTENT.format(pagerduty_key=self.model.config["pagerduty_key"])

    def build_pod_spec(self):
        """Builds the pod spec based on available info in datastore`."""

        config = self.model.config

        config_file_contents = self.build_config_file()

        # set image details based on what is defined in the charm configuation
        image_details = {"imagePath": config["alertmanager_image_path"]}

        ha_targets = []
        num_units = self.num_units()
        if num_units > 1:
            for i in range(num_units):
                cluster_address = UNIT_ADDRESS.format(
                    self.meta.name, i, self.meta.name, self.model.name
                )
                ha_targets.append(f"--cluster.peer={cluster_address}:{HA_PORT}")

        spec = {
            "version": 3,
            "containers": [
                {
                    "name": self.app.name,  # self.app.name is defined in metadata.yaml
                    "imageDetails": image_details,
                    "args": [
                        "--config.file=/etc/alertmanager/alertmanager.yaml",
                        "--storage.path=/alertmanager",
                        f'--web.listen-address=:{config["port"]}',
                    ]
                    + ha_targets,
                    "ports": [{"containerPort": config["port"], "protocol": "TCP"}],
                    "kubernetes": {
                        "readinessProbe": {
                            "httpGet": {"path": "/-/ready", "port": config["port"]},
                            "initialDelaySeconds": 10,
                            "timeoutSeconds": 30,
                        },
                        "livenessProbe": {
                            "httpGet": {"path": "/-/healthy", "port": config["port"]},
                            "initialDelaySeconds": 30,
                            "timeoutSeconds": 30,
                        },
                    },
                    # this where we define any files necessary for configuration
                    # Juju gives developers a nice way of directly defining what
                    # the contents of files should be.
                    # Note that "volumeConfig" is new in pod-spec v3 and is a
                    # replacement for "files"
                    "volumeConfig": [
                        {
                            "name": "config",
                            "mountPath": "/etc/alertmanager",
                            "files": [
                                {
                                    "path": "alertmanager.yaml",
                                    # this is a very basic configuration file with
                                    # some hard coded options for demonstration
                                    # consider adding this kind of information in
                                    # `config.yaml` in production charms
                                    "content": config_file_contents,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        return spec

    def num_units(self):
        relation = self.model.get_relation("alertmanager")
        # The relation does not list ourself as a unit so we must add 1
        return len(relation.units) + 1 if relation is not None else 1


if __name__ == "__main__":
    main(AlertmanagerCharm)

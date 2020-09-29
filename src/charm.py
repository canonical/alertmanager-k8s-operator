#!/usr/bin/env python3
# Copyright 2020 dylan
# See LICENSE file for licensing details.

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState
from ops.model import ActiveStatus, MaintenanceStatus

log = logging.getLogger(__name__)
CONFIG_CONTENT = """
route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 3h
  receiver: slack_prometheus
  routes:
  - match:
      severity: critical
      receiver: critical_alert
  - match:
      severity: warning
      receiver: slack_prometheus
inhibit_rules:
- source_match:
    severity: 'critical'
  target_match:
    severity: 'warning'
  equal: ['cluster', 'service']
receivers:
- name: critical_alert
  pagerduty_configs:
   - send_resolved:  true
     service_key: 'helloworld'
"""


class AlertmanagerCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        log.debug('Initializing charm.')
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_config_changed(self, _):
        """Set Juju / Kubernetes pod spec built from `_build_pod_spec()`."""

        # even though we won't be supporting peer relations in this tutorial
        # it is best practice to check whether this unit is the leader unit
        if not self.unit.is_leader():
            log.debug('Unit is not leader. Cannot set pod spec.')
            return

        # setting pod spec and associated logging
        self.unit.status = MaintenanceStatus('Building pod spec.')
        log.debug('Building pod spec.')

        pod_spec = self._build_pod_spec()
        self.model.pod.set_spec(pod_spec)

        self.unit.status = ActiveStatus()
        log.debug('Pod spec set successfully.')

    def _build_pod_spec(self):
        """Builds the pod spec based on available info in datastore`."""

        config = self.model.config

        # set image details based on what is defined in the charm configuation
        image_details = {
            'imagePath': config['alertmanager_image_path']
        }

        spec = {
            'version': 3,
            'containers': [{
                'name': self.app.name,  # self.app.name is defined in metadata.yaml
                'imageDetails': image_details,
                'ports': [{
                    'containerPort': 9093,
                    'protocol': 'TCP'
                }],

                # this where we define any files necessary for configuration
                # Juju gives developers a nice way of directly defining what
                # the contents of files should be.

                # Note that "volumeConfig" is new in pod-spec v3 and is a
                # replacement for "files"
                'volumeConfig': [{
                    'name': 'config',
                    'mountPath': '/etc/prometheus',
                    'files': [{
                        'path': 'alertmanager.yml',

                        # this is a very basic configuration file with
                        # some hard coded options for demonstration
                        # consider adding this kind of information in
                        # `config.yaml` in production charms
                        'content': CONFIG_CONTENT.format()
                    }],
                }],
            }]
        }

        return spec


if __name__ == "__main__":
    main(AlertmanagerCharm)

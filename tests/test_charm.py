# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import textwrap

from .helpers import network_get
from charm import AlertmanagerCharm, AlertmanagerAPIClient

import ops
from ops.testing import Harness
from ops.model import ActiveStatus

import yaml
import unittest
from unittest.mock import patch


# Things to test:
# - self.harness.charm._stored is updated (unless considered private impl. detail)


def mock_blank(*args, **kwargs):
    pass


def mock_pull(*args, **kwargs):
    return textwrap.dedent("""
            route:
              group_by: ['alertname']
              group_wait: 30s
              group_interval: 5m
              repeat_interval: 1h
              receiver: 'web.hook'
            receivers:
            - name: 'web.hook'
              webhook_configs:
              - url: 'http://127.0.0.1:5001/'
            inhibit_rules:
              - source_match:
                  severity: 'critical'
                target_match:
                  severity: 'warning'
                equal: ['alertname', 'dev', 'instance']
    """)


@patch('ops.testing._TestingPebbleClient.push', mock_blank)
@patch('ops.testing._TestingPebbleClient.pull', mock_pull)
@patch('ops.testing._TestingModelBackend.network_get', network_get)
class TestCharm(unittest.TestCase):
    container_name: str = "alertmanager"

    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.harness.set_leader(True)
        # self.harness.update_config({"pagerduty_key": "123"})

    def test_service_running_after_startup(self):
        # adding another unit because without it the harness returns `None` for
        # `self.model.get_relation(self._peer_relation_name)`
        relation_id = self.harness.add_relation("replicas", "alertmanager")
        self.harness.add_relation_unit(relation_id, "alertmanager/1")

        initial_plan = self.harness.get_container_pebble_plan(self.container_name)
        self.assertEqual(initial_plan.to_dict(), {})

        container = self.harness.model.unit.get_container(self.container_name)

        # Emit the PebbleReadyEvent carrying the alertmanager container
        self.harness.charm.on.alertmanager_pebble_ready.emit(container)

        # Get the plan now we've run PebbleReady
        updated_plan = self.harness.get_container_pebble_plan(self.container_name).to_dict()

        expected_plan = {
            "services": {
                self.harness.charm._service_name: {
                    "override": "replace",
                    "summary": "alertmanager service",
                    "command": "/bin/alertmanager "
                               "--config.file={} "
                               "--storage.path={} "
                               "--web.listen-address=:{} "
                               "--cluster.listen-address={} ".format(
                                self.harness.charm._config_path,
                                self.harness.charm._storage_path,
                                self.harness.charm._api_port,
                                ""
                               ),
                    "startup": "enabled",
                }
            },
        }

        self.assertDictEqual(expected_plan["services"], updated_plan["services"])

    @unittest.skip("")
    def test_config_changed(self):
        def get_config():
            pod_spec = self.harness.get_pod_spec()
            config_yaml = pod_spec[0]["containers"][0]["volumeConfig"][0]["files"][0][
                "content"
            ]
            return yaml.safe_load(config_yaml)

        self.harness.update_config({"pagerduty_key": "abc"})
        config = get_config()
        self.assertEqual(
            config["receivers"][0]["pagerduty_configs"][0]["service_key"], "abc"
        )

    @unittest.skip("")
    def test_port_change(self):
        container = self.harness.model.unit.get_container("alertmanager")
        self.harness.charm.on.alertmanager_pebble_ready.emit(container)

        rel_id = self.harness.add_relation("alerting", "prometheus")
        self.assertIsInstance(rel_id, int)
        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.harness.update_config({"port": "9096"})
        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.model.app.name)["port"],
            "9096",
        )

    @unittest.skip("")
    def test_bad_config(self):
        self.harness.update_config({"pagerduty_key": ""})
        self.assertIn(type(self.harness.model.unit.status), [ops.model.BlockedStatus,
                                                             ops.model.WaitingStatus])

    # TODO figure out how to test scaling up the application

    @unittest.skip("")
    def test_alertmanager_pebble_ready(self):
        # Check the initial Pebble plan is empty
        initial_plan = self.harness.get_container_pebble_plan("alertmanager")
        self.assertEqual(initial_plan.to_dict(), {})
        # Expected plan after Pebble ready with default config

        expected_plan = {
            "services": {
                "alertmanager": {
                    "override": "replace",
                    "summary": "alertmanager service",
                    "command": "/bin/alertmanager "
                               "--config.file=/etc/alertmanager/alertmanager.yaml "
                               "--storage.path=/alertmanager",
                    "startup": "enabled",
                    # "environment": {"thing": self.model.config["thing"]},
                }
            },
        }

        # Get the alertmanager container from the model
        container = self.harness.model.unit.get_container("alertmanager")
        # Emit the PebbleReadyEvent carrying the alertmanager container
        self.harness.charm.on.alertmanager_pebble_ready.emit(container)
        # Get the plan now we've run PebbleReady
        updated_plan = self.harness.get_container_pebble_plan("alertmanager").to_dict()
        # Check we've got the plan we expected
        self.assertEqual(expected_plan, updated_plan)
        # Check the service was started
        service = self.harness.model.unit.get_container("alertmanager").get_service("alertmanager")
        self.assertTrue(service.is_running())
        # Ensure we set an ActiveStatus with no message
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())


class TestAlertmanagerAPIClient(unittest.TestCase):
    def setUp(self):
        self.api = AlertmanagerAPIClient("address", 12345)

    def test_base_url(self):
        self.assertEqual("http://address:12345/", self.api.base_url)

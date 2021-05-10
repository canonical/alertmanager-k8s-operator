# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
import ops
import yaml

from ops.testing import Harness
from ops.model import ActiveStatus
from charm import AlertmanagerCharm

from unittest.mock import patch


def mock_blank(*args, **kwargs):
    pass


@patch('ops.testing._TestingPebbleClient.push', mock_blank)
@patch('ops.testing._TestingPebbleClient.make_dir', mock_blank)
class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_leader(True)
        #self.harness.update_config({"pagerduty_key": "123"})

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

    #@unittest.skip("")
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
        self.assertEqual(type(self.harness.model.unit.status), ops.model.BlockedStatus)

    # TODO figure out how to test scaling up the application

    def test_alertmanager_pebble_ready(self):
        # Check the initial Pebble plan is empty
        initial_plan = self.harness.get_container_pebble_plan("alertmanager")
        self.assertEqual(initial_plan.to_yaml(), "{}\n")
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

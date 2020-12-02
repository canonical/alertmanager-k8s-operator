# Copyright 2020 dylan
# See LICENSE file for licensing details.

import unittest
import ops
import yaml

from ops.testing import Harness
from charm import AlertmanagerCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_leader(True)
        self.harness.update_config({"pagerduty_key": "123"})

    def test_config_changed(self):
        self.harness.update_config({"pagerduty_key": "abc"})
        config = self.get_config()
        self.assertEqual(
            config["receivers"][0]["pagerduty_configs"][0]["service_key"], "abc"
        )

    def test_port_change(self):
        rel_id = self.harness.add_relation("alerting", "prometheus")
        self.assertIsInstance(rel_id, int)
        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.harness.update_config({"port": "9096"})
        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.model.app.name)["port"],
            "9096",
        )

    def test_bad_config(self):
        self.harness.update_config({"pagerduty_key": ""})
        self.assertEqual(type(self.harness.model.unit.status), ops.model.BlockedStatus)

    def get_config(self):
        pod_spec = self.harness.get_pod_spec()
        config_yaml = pod_spec[0]["containers"][0]["volumeConfig"][0]["files"][0][
            "content"
        ]
        return yaml.safe_load(config_yaml)

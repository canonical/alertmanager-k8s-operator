# Copyright 2020 dylan
# See LICENSE file for licensing details.

import unittest
import yaml

from ops.testing import Harness
from charm import AlertmanagerCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_leader(True)

    def test_config_changed(self):
        self.harness.update_config({'pagerduty_key': 'abc'})
        config = self.get_config()
        self.assertEqual(config['receivers'][0]['pagerduty_configs'][0]['service_key'], 'abc')

    def get_config(self):
        pod_spec = self.harness.get_pod_spec()
        config_yaml = pod_spec[0]['containers'][0]['volumeConfig'][0]['files'][0]['content']
        return(yaml.safe_load(config_yaml))

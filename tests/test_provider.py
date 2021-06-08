# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from .dummy import DummyCharmForTestingProvider

from ops.testing import Harness

import unittest
from unittest.mock import patch


class TestProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyCharmForTestingProvider)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_relation_joined(self):
        rel_id = self.harness.add_relation(relation_name="alerting", remote_app="prometheus-k8s")

        rel = self.harness.charm.framework.model.get_relation("alerting", rel_id)
        self.assertEqual({}, rel.data[self.harness.charm.unit])

        def network_get(*args, **kwargs):
            """patch for the not-yet-implemented testing backend needed for
            self.model.get_binding(event.relation).network.bind_address
            """
            return {'bind-addresses': [
                {
                    'mac-address': '', 'interface-name': '',
                    'addresses': [{'hostname': '', 'value': '10.1.157.116', 'cidr': ''}]
                }
            ], 'egress-subnets': ['10.152.183.65/32'], 'ingress-addresses': ['10.152.183.65']}

        with patch('ops.testing._TestingModelBackend.network_get', network_get):
            self.harness.charm.on["alerting"].relation_joined.emit(rel)

        self.assertEqual({'public_address': '10.1.157.116'}, rel.data[self.harness.charm.unit])

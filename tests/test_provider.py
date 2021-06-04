# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

from provider import AlertmanagerProvider

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

import unittest
from typing import List, Union


class DummyCharmForTesting(CharmBase):
    """A class for mimicking the bare AlertmanagerCharm functionality needed to test the provider.
    """
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.provider = AlertmanagerProvider(self, "alertmanager")

        self._stored.set_default(
            config_hash=None,
            pebble_ready="yes",
            started="yes",
            launched_with_peers=None,
            config_valid="yes",
        )

    def get_api_addresses(self) -> List[Union[str, None]]:
        return ["1.1.1.1:1111", "3.3.3.3:3333", "2.2.2.2:2222"]


class TestProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyCharmForTesting)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_relation_joined(self):
        rel_id = self.harness.add_relation(relation_name="alerting",
                                           remote_app="alertmanager-k8s")

        rel_data = self.harness.get_relation_data(rel_id, "alertmanager-k8s")
        self.assertEqual({}, rel_data)

        # rel = self.harness.charm.framework.model.get_relation("alerting", rel_id)
        # TODO how to patch underlying call to
        #  self.model.get_binding(event.relation).network.bind_address
        # self.harness.charm.on["alerting"].relation_joined.emit(rel)

        rel_data = self.harness.get_relation_data(rel_id, "alertmanager-k8s")
        # self.assertEqual(..., rel_data)

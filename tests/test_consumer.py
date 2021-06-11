# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from .helpers import DummyCharmForTestingConsumer

from ops.testing import Harness

import unittest

# from unittest.mock import patch


@unittest.skip("not ready")
class TestConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyCharmForTestingConsumer)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_relation_changed(self):
        # container name has to be `alertmanager` because that's what the harness expects based on
        # metadata.yaml
        container = self.harness.model.unit.get_container("alertmanager")

        # Emit the PebbleReadyEvent carrying the alertmanager container

        self.harness.charm.on.alertmanager_pebble_ready.emit(container)

        rel_id = self.harness.add_relation(relation_name="alerting", remote_app="alertmanager-k8s")
        # self.harness.add_relation_unit(rel_id, "alertmanager-k8s/0")
        self.harness.add_relation_unit(rel_id, "prometheus-k8s/0")
        rel = self.harness.charm.framework.model.get_relation("alerting", rel_id)

        self.assertEqual(0, self.harness.charm._stored.on_available_emitted)
        self.harness.update_relation_data(
            rel_id, "prometheus-k8s/0", {"public_address": "1.1.1.1"}
        )
        self.harness.charm.on["alerting"].relation_changed.emit(rel)
        self.assertEqual(1, self.harness.charm._stored.on_available_emitted)

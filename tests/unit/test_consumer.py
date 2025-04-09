#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import textwrap
import unittest

import ops
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True  # pyright: ignore


class SampleConsumerCharm(CharmBase):
    """Mimic bare functionality of AlertmanagerCharm needed to test the consumer."""

    # define custom metadata - without this the harness would parse the metadata.yaml in this repo,
    # which would result in expressions like self.harness.model.app.name to return
    # "alertmanager-k8s", which is not what we want in a consumer test
    metadata_yaml = textwrap.dedent(
        """
        name: SampleConsumerCharm
        containers:
          consumer-charm:
            resource: consumer-charm-image
        resources:
          consumer-charm-image:
            type: oci-image
        requires:
          alerting:
            interface: alertmanager_dispatch
        peers:
          replicas:
            interface: consumer_charm_replica
        """
    )
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        # relation name must match metadata
        self.alertmanager_lib = AlertmanagerConsumer(self, relation_name="alerting")

        self.framework.observe(
            self.alertmanager_lib.on.cluster_changed, self._on_alertmanager_cluster_changed
        )

        self._stored.set_default(alertmanagers=[], cluster_changed_emitted=0)

    def _on_alertmanager_cluster_changed(self, _):
        self._stored.cluster_changed_emitted += 1
        self._stored.alertmanagers = self.alertmanager_lib.get_cluster_info()


class TestConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(SampleConsumerCharm, meta=SampleConsumerCharm.metadata_yaml)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def _relate_to_alertmanager(self) -> int:
        """Create relation between 'this app' and a hypothetical (remote) alertmanager."""
        rel_id = self.harness.add_relation(relation_name="alerting", remote_app="am")
        return rel_id

    def _add_alertmanager_units(self, rel_id: int, num_units: int, start_with=0):
        for i in range(start_with, start_with + num_units):
            remote_unit_name = f"am/{i}"
            self.harness.add_relation_unit(rel_id, remote_unit_name)
            self.harness.update_relation_data(
                rel_id, remote_unit_name, {"public_address": f"10.20.30.{i}"}
            )

        return rel_id

    def test_cluster_updated_after_alertmanager_units_join(self):
        # before
        self.assertEqual(set(), self.harness.charm.alertmanager_lib.get_cluster_info())
        num_events = self.harness.charm._stored.cluster_changed_emitted

        # add relation
        rel_id = self._relate_to_alertmanager()
        self._add_alertmanager_units(rel_id, num_units=2)

        # after
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        self.assertSetEqual(
            {"http://10.20.30.0", "http://10.20.30.1"},
            self.harness.charm.alertmanager_lib.get_cluster_info(),
        )

        num_events = self.harness.charm._stored.cluster_changed_emitted

        # add another unit
        self._add_alertmanager_units(rel_id, num_units=1, start_with=2)
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        self.assertSetEqual(
            {"http://10.20.30.0", "http://10.20.30.1", "http://10.20.30.2"},
            self.harness.charm.alertmanager_lib.get_cluster_info(),
        )

    def test_cluster_updated_after_alertmanager_unit_leaves(self):
        num_events = self.harness.charm._stored.cluster_changed_emitted

        # add relation
        rel_id = self._relate_to_alertmanager()
        self._add_alertmanager_units(rel_id, num_units=4)
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        before = self.harness.charm.alertmanager_lib.get_cluster_info()
        self.assertEqual(len(before), 4)

        num_events = self.harness.charm._stored.cluster_changed_emitted

        # remove alertmanager units
        self.harness.remove_relation_unit(rel_id, "am/3")
        self.harness.remove_relation_unit(rel_id, "am/2")
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        after = self.harness.charm.alertmanager_lib.get_cluster_info()
        self.assertSetEqual(after, {"http://10.20.30.0", "http://10.20.30.1"})

        num_events = self.harness.charm._stored.cluster_changed_emitted

        # remove all remaining units
        self.harness.remove_relation_unit(rel_id, "am/1")
        self.harness.remove_relation_unit(rel_id, "am/0")
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        after = self.harness.charm.alertmanager_lib.get_cluster_info()
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        self.assertSetEqual(after, set())

    def test_cluster_is_empty_after_relation_breaks(self):
        # add relation
        rel_id = self._relate_to_alertmanager()
        self._add_alertmanager_units(rel_id, num_units=4)
        before = self.harness.charm.alertmanager_lib.get_cluster_info()
        self.assertEqual(len(before), 4)

        num_events = self.harness.charm._stored.cluster_changed_emitted

        # remove relation
        self.harness.remove_relation(rel_id)
        after = self.harness.charm.alertmanager_lib.get_cluster_info()
        self.assertGreater(self.harness.charm._stored.cluster_changed_emitted, num_events)
        self.assertSetEqual(set(), after)

    def test_relation_changed(self):
        # add relation
        rel_id = self._relate_to_alertmanager()
        self._add_alertmanager_units(rel_id, num_units=2)

        # update remote unit's relation data (emulates upgrade-charm)
        self.harness.update_relation_data(rel_id, "am/1", {"public_address": "90.80.70.60"})
        self.assertSetEqual(
            {"http://10.20.30.0", "http://90.80.70.60"},
            self.harness.charm.alertmanager_lib.get_cluster_info(),
        )

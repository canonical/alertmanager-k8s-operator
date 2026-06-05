#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the AlertmanagerConsumer library using Scenario."""

import dataclasses
import json

import pytest
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer
from ops.charm import CharmBase
from ops.testing import Container, Context, PeerRelation, Relation, State

CONSUMER_METADATA = {
    "name": "sample-consumer-charm",
    "containers": {
        "consumer-charm": {"resource": "consumer-charm-image"},
    },
    "resources": {
        "consumer-charm-image": {"type": "oci-image"},
    },
    "requires": {
        "alerting": {"interface": "alertmanager_dispatch"},
    },
    "peers": {
        "replicas": {"interface": "consumer_charm_replica"},
    },
}


class SampleConsumerCharm(CharmBase):
    """Mimic bare functionality of AlertmanagerCharm needed to test the consumer.

    Instead of using StoredState (which isn't easily accessible in Scenario),
    we track state via peer relation data.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.alertmanager_lib = AlertmanagerConsumer(self, relation_name="alerting")

        self.framework.observe(
            self.alertmanager_lib.on.cluster_changed, self._on_alertmanager_cluster_changed
        )

    def _on_alertmanager_cluster_changed(self, _):
        """When cluster changes, store the current state in peer relation data."""
        if peer := self.model.get_relation("replicas"):
            cluster_info = sorted(self.alertmanager_lib.get_cluster_info())
            peer.data[self.unit]["cluster_info"] = json.dumps(cluster_info)


@pytest.fixture
def consumer_context():
    """Create a Context for the sample consumer charm."""
    return Context(charm_type=SampleConsumerCharm, meta=CONSUMER_METADATA)


@pytest.fixture
def container() -> Container:
    return Container("consumer-charm", can_connect=True)


@pytest.fixture
def peer_relation() -> PeerRelation:
    return PeerRelation("replicas", id=0)


def make_alerting_relation(
    rel_id: int = 10,  # Use different ID range than peer relation
    remote_units_data: dict | None = None,
) -> Relation:
    """Create an alerting relation with optional remote unit data."""
    return Relation(
        "alerting",
        id=rel_id,
        remote_app_name="am",
        remote_units_data=remote_units_data or {},
    )


def get_cluster_info_from_state(state: State) -> list[str]:
    """Extract the stored cluster info from peer relation data."""
    peer = state.get_relations("replicas")[0]
    cluster_info_json = peer.local_unit_data.get("cluster_info", "[]")
    return json.loads(cluster_info_json)


class TestConsumer:
    """Tests for the AlertmanagerConsumer library."""

    def test_cluster_updated_after_alertmanager_units_join(
        self, consumer_context: Context, container: Container, peer_relation: PeerRelation
    ):
        """Test that cluster info is updated when alertmanager units join."""
        # Start with peer relation but no alerting relation
        state = State(leader=True, containers=[container], relations=[peer_relation])
        state = consumer_context.run(consumer_context.on.start(), state)

        # Before: no alertmanagers (no cluster_changed event fired yet)
        assert get_cluster_info_from_state(state) == []

        # Add alerting relation with 2 units
        alerting_rel = make_alerting_relation(
            remote_units_data={
                0: {"public_address": "10.20.30.0"},
                1: {"public_address": "10.20.30.1"},
            },
        )
        state = dataclasses.replace(state, relations=[peer_relation, alerting_rel])
        state = consumer_context.run(consumer_context.on.relation_changed(alerting_rel), state)

        # After: should have 2 alertmanagers
        cluster_info = get_cluster_info_from_state(state)
        assert sorted(cluster_info) == ["http://10.20.30.0", "http://10.20.30.1"]

        # Add a third unit
        alerting_rel_three = make_alerting_relation(
            remote_units_data={
                0: {"public_address": "10.20.30.0"},
                1: {"public_address": "10.20.30.1"},
                2: {"public_address": "10.20.30.2"},
            },
        )
        state = dataclasses.replace(
            state, relations=[state.get_relations("replicas")[0], alerting_rel_three]
        )
        state = consumer_context.run(
            consumer_context.on.relation_changed(alerting_rel_three), state
        )

        cluster_info = get_cluster_info_from_state(state)
        assert sorted(cluster_info) == [
            "http://10.20.30.0",
            "http://10.20.30.1",
            "http://10.20.30.2",
        ]

    def test_cluster_updated_after_alertmanager_unit_leaves(
        self, consumer_context: Context, container: Container, peer_relation: PeerRelation
    ):
        """Test that cluster info is updated when alertmanager units leave."""
        # Start with 4 units
        alerting_rel = make_alerting_relation(
            remote_units_data={i: {"public_address": f"10.20.30.{i}"} for i in range(4)},
        )
        state = State(leader=True, containers=[container], relations=[peer_relation, alerting_rel])
        state = consumer_context.run(consumer_context.on.relation_changed(alerting_rel), state)

        assert len(get_cluster_info_from_state(state)) == 4

        # Remove 2 units via relation-departed
        alerting_rel_two = make_alerting_relation(
            remote_units_data={
                0: {"public_address": "10.20.30.0"},
                1: {"public_address": "10.20.30.1"},
            },
        )
        state = dataclasses.replace(
            state, relations=[state.get_relations("replicas")[0], alerting_rel_two]
        )

        # Simulate relation-departed events
        state = consumer_context.run(
            consumer_context.on.relation_departed(alerting_rel_two, remote_unit=3), state
        )
        state = consumer_context.run(
            consumer_context.on.relation_departed(alerting_rel_two, remote_unit=2), state
        )

        cluster_info = get_cluster_info_from_state(state)
        assert sorted(cluster_info) == ["http://10.20.30.0", "http://10.20.30.1"]

        # Remove all remaining units
        alerting_rel_empty = make_alerting_relation(remote_units_data={})
        state = dataclasses.replace(
            state, relations=[state.get_relations("replicas")[0], alerting_rel_empty]
        )
        state = consumer_context.run(
            consumer_context.on.relation_departed(alerting_rel_empty, remote_unit=1), state
        )
        state = consumer_context.run(
            consumer_context.on.relation_departed(alerting_rel_empty, remote_unit=0), state
        )

        assert get_cluster_info_from_state(state) == []

    def test_cluster_is_empty_after_relation_breaks(
        self, consumer_context: Context, container: Container, peer_relation: PeerRelation
    ):
        """Test that cluster info is empty after relation is removed."""
        # Start with 4 units
        alerting_rel = make_alerting_relation(
            remote_units_data={i: {"public_address": f"10.20.30.{i}"} for i in range(4)},
        )
        state = State(leader=True, containers=[container], relations=[peer_relation, alerting_rel])
        state = consumer_context.run(consumer_context.on.relation_changed(alerting_rel), state)

        assert len(get_cluster_info_from_state(state)) == 4

        # Get the alerting relation from state and fire relation_broken on it
        # Note: for relation_broken, the relation should still be in state during the event
        alerting_rel_from_state = state.get_relations("alerting")[0]
        state = consumer_context.run(
            consumer_context.on.relation_broken(alerting_rel_from_state), state
        )

        # After relation broken, cluster info should be empty
        assert get_cluster_info_from_state(state) == []

    def test_relation_changed(
        self, consumer_context: Context, container: Container, peer_relation: PeerRelation
    ):
        """Test that cluster info is updated when remote unit data changes."""
        # Start with 2 units
        alerting_rel = make_alerting_relation(
            remote_units_data={
                0: {"public_address": "10.20.30.0"},
                1: {"public_address": "10.20.30.1"},
            },
        )
        state = State(leader=True, containers=[container], relations=[peer_relation, alerting_rel])
        state = consumer_context.run(consumer_context.on.relation_changed(alerting_rel), state)

        cluster_info = get_cluster_info_from_state(state)
        assert sorted(cluster_info) == ["http://10.20.30.0", "http://10.20.30.1"]

        # Update unit 1's address (simulates upgrade-charm)
        alerting_rel_updated = make_alerting_relation(
            remote_units_data={
                0: {"public_address": "10.20.30.0"},
                1: {"public_address": "90.80.70.60"},
            },
        )
        state = dataclasses.replace(
            state, relations=[state.get_relations("replicas")[0], alerting_rel_updated]
        )
        state = consumer_context.run(
            consumer_context.on.relation_changed(alerting_rel_updated), state
        )

        cluster_info = get_cluster_info_from_state(state)
        assert sorted(cluster_info) == ["http://10.20.30.0", "http://90.80.70.60"]

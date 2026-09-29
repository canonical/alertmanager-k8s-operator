# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the charm survives the lifecycle events it does not otherwise assert on."""

import dataclasses

import pytest
from ops.testing import Context, Relation, State


@pytest.mark.parametrize("event", ["install", "start", "update_status", "stop", "remove"])
def test_charm_handles_lifecycle_events_without_erroring(
    context: Context, base_state: State, event: str
):
    # GIVEN a ready charm
    # WHEN a lifecycle event fires
    # THEN the charm does not raise
    context.run(getattr(context.on, event)(), base_state)


def test_charm_handles_a_departing_peer_without_erroring(
    context: Context, base_state: State, peer_relation
):
    # GIVEN a ready charm with a peer
    # WHEN that peer departs
    # THEN the charm does not raise
    context.run(context.on.relation_departed(peer_relation, remote_unit=2), base_state)


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
def test_every_related_app_gets_the_same_alerting_data(
    context: Context, base_state: State, leader: bool
):
    """Alertmanager advertises itself identically to each consumer, regardless of who asks."""
    # GIVEN a charm related to several prometheus apps
    prom_relations = [Relation("alerting", remote_app_name=f"prom-{i}") for i in range(3)]
    state_in = dataclasses.replace(
        base_state, leader=leader, relations=[*base_state.relations, *prom_relations]
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN all "alerting" relations carry identical data
    relations = state.get_relations("alerting")
    assert len({tuple(sorted(r.local_unit_data.items())) for r in relations}) == 1
    assert len({tuple(sorted(r.local_app_data.items())) for r in relations}) == 1

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: a consumer charm tracks the cluster of alertmanager units it is related to."""

from typing import Iterable, Set

import pytest
from charms.alertmanager_k8s.v1.alertmanager_dispatch import (
    AlertmanagerConsumer,
    ClusterChanged,
)
from ops.charm import CharmBase
from ops.testing import Context, Relation, State


class SampleConsumerCharm(CharmBase):
    """Mimic bare functionality of AlertmanagerCharm needed to test the consumer."""

    # define custom metadata - without this the context would parse the charmcraft.yaml in this
    # repo, which would result in expressions like self.model.app.name to return
    # "alertmanager-k8s", which is not what we want in a consumer test
    metadata = {
        "name": "SampleConsumerCharm",
        "containers": {"consumer-charm": {"resource": "consumer-charm-image"}},
        "resources": {"consumer-charm-image": {"type": "oci-image"}},
        "requires": {"alerting": {"interface": "alertmanager_dispatch"}},
        "peers": {"replicas": {"interface": "consumer_charm_replica"}},
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        # relation name must match metadata
        self.alertmanager_lib = AlertmanagerConsumer(self, relation_name="alerting")


@pytest.fixture
def context() -> Context:
    return Context(SampleConsumerCharm, meta=SampleConsumerCharm.metadata)


def alerting(*unit_ids: int, addresses: Iterable[str] = ()) -> Relation:
    """A relation to a remote alertmanager app whose units have the given addresses.

    By default unit `i` is reachable at `10.20.30.i`.
    """
    remote_units_data = (
        {i: {"public_address": address} for i, address in zip(unit_ids, addresses)}
        if addresses
        else {i: {"public_address": f"10.20.30.{i}"} for i in unit_ids}
    )
    return Relation("alerting", id=1, remote_app_name="am", remote_units_data=remote_units_data)


def cluster_info(context: Context, state: State) -> Set[str]:
    """The cluster the consumer lib sees, given a state."""
    with context(context.on.update_status(), state) as mgr:
        return mgr.charm.alertmanager_lib.get_cluster_info()


def cluster_changed_emitted(context: Context) -> bool:
    return any(isinstance(e, ClusterChanged) for e in context.emitted_events)


def test_cluster_is_empty_without_an_alerting_relation(context: Context):
    # GIVEN a consumer with no alerting relation
    state = State(leader=True)

    # THEN it sees an empty cluster
    assert cluster_info(context, state) == set()


def test_cluster_holds_the_related_alertmanager_units(context: Context):
    # GIVEN a consumer related to an alertmanager with two units
    state = State(leader=True, relations=[alerting(0, 1)])

    # THEN it sees both units in the cluster
    assert cluster_info(context, state) == {"http://10.20.30.0", "http://10.20.30.1"}


def test_cluster_grows_when_an_alertmanager_unit_joins(context: Context):
    # GIVEN an alerting relation with a third alertmanager unit present
    relation = alerting(0, 1, 2)

    # WHEN that unit publishes its address
    state = context.run(
        context.on.relation_changed(relation, remote_unit=2),
        State(leader=True, relations=[relation]),
    )

    # THEN a ClusterChanged event is emitted
    assert cluster_changed_emitted(context)

    # AND the new unit is part of the cluster
    assert cluster_info(context, state) == {
        "http://10.20.30.0",
        "http://10.20.30.1",
        "http://10.20.30.2",
    }


@pytest.mark.parametrize(
    "departing_unit, remaining",
    [
        (3, {"http://10.20.30.0", "http://10.20.30.1", "http://10.20.30.2"}),
        (2, {"http://10.20.30.0", "http://10.20.30.1"}),
        (1, {"http://10.20.30.0"}),
        (0, set()),
    ],
)
def test_cluster_shrinks_when_an_alertmanager_unit_departs(
    context: Context, departing_unit: int, remaining: Set[str]
):
    # GIVEN an alerting relation whose remaining units are those below the departing one
    relation = alerting(*range(departing_unit))

    # WHEN that unit departs
    state = context.run(
        context.on.relation_departed(
            relation, remote_unit=departing_unit, departing_unit=departing_unit
        ),
        State(leader=True, relations=[relation]),
    )

    # THEN a ClusterChanged event is emitted
    assert cluster_changed_emitted(context)

    # AND only the remaining units are in the cluster
    assert cluster_info(context, state) == remaining


def test_cluster_is_empty_after_the_alerting_relation_breaks(context: Context):
    # GIVEN a consumer related to an alertmanager with four units
    relation = alerting(0, 1, 2, 3)
    assert len(cluster_info(context, State(leader=True, relations=[relation]))) == 4

    # WHEN the relation breaks
    context.run(context.on.relation_broken(relation), State(leader=True, relations=[relation]))

    # THEN a ClusterChanged event is emitted
    assert cluster_changed_emitted(context)

    # AND without the relation the cluster is empty
    assert cluster_info(context, State(leader=True)) == set()


def test_cluster_tracks_an_updated_unit_address(context: Context):
    # GIVEN an alertmanager unit that has moved to a different address
    relation = alerting(0, 1, addresses=["10.20.30.0", "90.80.70.60"])

    # WHEN it republishes its address (as happens on upgrade-charm)
    state = context.run(
        context.on.relation_changed(relation, remote_unit=1),
        State(leader=True, relations=[relation]),
    )

    # THEN a ClusterChanged event is emitted
    assert cluster_changed_emitted(context)

    # AND the cluster reflects the new address
    assert cluster_info(context, state) == {"http://10.20.30.0", "http://90.80.70.60"}

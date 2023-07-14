# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Context, Relation, State

"""Some brute-force tests, so that other tests can remain focused."""


def test_startup_shutdown_sequence(context: Context):
    state = begin_with_initial_hooks_isolated(context)
    state = context.run("update-status", state)

    for peer_rel in state.get_relations("replicas"):
        state = context.run(peer_rel.departed_event, state)

    state = context.run("stop", state)
    context.run("remove", state)


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
class TestAlertingRelationDataUniformity:
    """Scenario: The charm is related to several different prometheus apps."""

    @pytest.fixture
    def post_startup(self, context, fqdn, leader) -> State:
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = begin_with_initial_hooks_isolated(context, leader=leader)

            # Add several relations TODO: how to obtain the next rel_id automatically?
            prom_rels = [Relation("alerting", relation_id=rel_id) for rel_id in (10, 11, 12)]
            for prom_rel in prom_rels:
                state = add_relation_sequence(context, state, prom_rel)
            return state

    def test_relation_data_is_the_same_for_all_related_apps(self, post_startup, fqdn):
        # GIVEN an isolated alertmanager charm after the startup sequence is complete
        state = post_startup

        # THEN the "alerting" relation data has the same contents for all related apps
        relations = state.get_relations("alerting")
        for i in range(1, len(relations)):
            assert relations[0].local_unit_data == relations[i].local_unit_data
            assert relations[0].local_app_data == relations[i].local_app_data

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the charm forwards its logs to a related loki, and copes when that relation goes."""

import dataclasses

import pytest
from ops.model import ActiveStatus
from ops.testing import Context, Relation, State


@pytest.fixture
def logging_relation() -> Relation:
    return Relation("logging", remote_app_name="loki")


def test_charm_is_active_with_a_logging_relation(
    context: Context, base_state: State, logging_relation
):
    # GIVEN a charm related to loki
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, logging_relation])

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the charm is active
    assert isinstance(state.unit_status, ActiveStatus)


def test_charm_handles_a_departing_loki_unit_without_erroring(
    context: Context, base_state: State, logging_relation
):
    # GIVEN a charm related to loki
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, logging_relation])

    # WHEN loki's unit departs
    # THEN the charm does not raise
    context.run(context.on.relation_departed(logging_relation, remote_unit=0), state_in)


def test_charm_is_active_after_the_logging_relation_is_removed(
    context: Context, base_state: State, logging_relation
):
    # GIVEN a charm that was related to loki
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, logging_relation])
    state = context.run(context.on.relation_broken(logging_relation), state_in)

    # WHEN the relation is gone and the charm reconciles
    state = dataclasses.replace(
        state, relations=[r for r in state.relations if r.id != logging_relation.id]
    )
    state = context.run(context.on.update_status(), state)

    # THEN the charm is active
    assert isinstance(state.unit_status, ActiveStatus)

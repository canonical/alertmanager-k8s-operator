# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the logging (log forwarding) relation."""

import dataclasses

from helpers import begin_with_initial_hooks_isolated
from ops.testing import Context, Relation


def test_charm_starts_with_logging_relation(context: Context):
    """The charm should handle a logging relation without errors."""
    state = begin_with_initial_hooks_isolated(context)

    logging_rel = Relation("logging")
    state_with_logging = dataclasses.replace(state, relations=[*state.relations, logging_rel])
    state_after = context.run(context.on.relation_created(logging_rel), state_with_logging)
    context.run(context.on.update_status(), state_after)


def test_charm_starts_without_logging_relation(context: Context):
    """The charm should start fine without a logging relation."""
    state = begin_with_initial_hooks_isolated(context)
    context.run(context.on.update_status(), state)

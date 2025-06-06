#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import dataclasses
from unittest.mock import patch

from ops.testing import Container, Context, Exec, PeerRelation, Relation, State


def no_op(*_, **__) -> None:
    pass


def tautology(*_, **__) -> bool:
    return True


def cli_arg(plan, cli_opt):
    plan_dict = plan.to_dict()
    args = plan_dict["services"]["alertmanager"]["command"].split()
    for arg in args:
        opt_list = arg.split("=")
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None


k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=tautology,
    is_ready=tautology,
)


def begin_with_initial_hooks_isolated(context: Context, *, leader: bool = True) -> State:
    container = Container(
        "alertmanager",
        can_connect=False,
        execs={
            Exec(["update-ca-certificates", "--fresh"]),
            Exec(
                ["alertmanager", "--version"],
                stdout="alertmanager, version 0.23.0 (branch: HEAD, ...",
            ),
            Exec(["/usr/bin/amtool", "check-config", "/etc/alertmanager/alertmanager.yml"]),
        },
    )
    state = State(config={"config_file": ""}, containers=[container])
    peer_rel = PeerRelation("replicas")

    state = context.run(context.on.install(), state)

    state = dataclasses.replace(state, relations=[peer_rel])
    state = context.run(context.on.relation_created(peer_rel), state)

    if leader:
        state = dataclasses.replace(state, leader=True)
        state = context.run(context.on.leader_elected(), state)
    else:
        state = dataclasses.replace(state, leader=False)

    state = context.run(context.on.config_changed(), state)

    # state = state.with_can_connect("alertmanger")
    container = dataclasses.replace(container, can_connect=True)
    state = dataclasses.replace(state, containers=[container])
    state = context.run(context.on.pebble_ready(container), state)

    state = context.run(context.on.start(), state)

    return state


def add_relation_sequence(context: Context, state: State, relation: Relation):
    """Helper to simulate a relation-added sequence."""
    # TODO consider adding to scenario.sequences
    state_with_relation = dataclasses.replace(state, relations={*state.relations, relation})
    state_after_relation_created = context.run(context.on.relation_created(relation), state_with_relation)
    state_after_relation_joined = context.run(context.on.relation_joined(relation), state_after_relation_created)
    state_after_relation_changed = context.run(
        context.on.relation_changed(state_after_relation_joined.get_relation(relation.id)),
        state_after_relation_joined,
    )
    return state_after_relation_changed

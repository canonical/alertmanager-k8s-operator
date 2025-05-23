#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

from unittest.mock import patch

from scenario import Container, Context, ExecOutput, PeerRelation, Relation, State


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
        exec_mock={
            ("update-ca-certificates", "--fresh"): ExecOutput(  # this is the command we're mocking
                return_code=0,  # this data structure contains all we need to mock the call.
                stdout="OK",
            )
        },
    )
    state = State(config={"config_file": ""}, containers=[container])
    peer_rel = PeerRelation("replicas")

    state = context.run("install", state)

    state = state.replace(relations=[peer_rel])
    state = context.run(peer_rel.created_event, state)

    if leader:
        state = state.replace(leader=True)
        state = context.run("leader-elected", state)
    else:
        state = state.replace(leader=False)
        state = context.run("leader-settings-changed", state)

    state = context.run("config-changed", state)

    # state = state.with_can_connect("alertmanger")
    container = container.replace(can_connect=True)
    state = state.replace(containers=[container])
    state = context.run(container.pebble_ready_event, state)

    state = context.run("start", state)

    return state


def add_relation_sequence(context: Context, state: State, relation: Relation):
    """Helper to simulate a relation-added sequence."""
    # TODO consider adding to scenario.sequences
    state_with_relation = state.replace(relations=state.relations + [relation])
    state_after_relation_created = context.run(relation.created_event, state_with_relation)
    state_after_relation_joined = context.run(relation.joined_event, state_after_relation_created)
    state_after_relation_changed = context.run(relation.changed_event, state_after_relation_joined)
    return state_after_relation_changed

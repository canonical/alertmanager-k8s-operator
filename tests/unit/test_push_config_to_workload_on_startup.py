#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the charm renders alertmanager's config files before starting the workload."""

import dataclasses

import pytest
import validators
import yaml
from helpers import CONTAINER_NAME, command_of, workload_file
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Context, State


@pytest.mark.parametrize("is_leader", [True, False])
def test_config_is_rendered_for_a_single_unit_cluster(
    context: Context, base_state: State, alertmanager_charm, is_leader: bool
):
    """Scenario: the current unit is the only unit present."""
    # GIVEN a single-unit deployment
    state_in = dataclasses.replace(base_state, leader=is_leader)
    assert state_in.planned_units == 1

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN amtool is pointed at a valid alertmanager url
    amtool_config = yaml.safe_load(
        workload_file(context, state, alertmanager_charm._amtool_config_path)
    )
    assert validators.url(amtool_config["alertmanager.url"], simple_host=True)

    # AND alertmanager's own config is rendered
    am_config = yaml.safe_load(workload_file(context, state, alertmanager_charm._config_path))
    assert am_config.keys() >= {"global", "route", "receivers"}

    # AND the workload is started against that config
    command = command_of(state)
    assert f"--config.file={alertmanager_charm._config_path}" in command

    # AND no cluster peers are configured, since there are none
    assert "--cluster.peer=" not in command


def test_peers_are_configured_for_a_multi_unit_cluster(
    context: Context, base_state: State, peer_relation
):
    """Scenario: the current unit is part of a multi-unit cluster."""
    # GIVEN a three-unit deployment whose peers have published their addresses
    peers = dataclasses.replace(
        peer_relation,
        peers_data={unit: {"private_address": f"http://fqdn-{unit}"} for unit in (1, 2)},
    )
    state_in = dataclasses.replace(
        base_state, leader=False, relations=[peers], planned_units=3
    )

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(peers, remote_unit=1), state_in)

    # THEN the workload is started with cluster peers
    assert "--cluster.peer=" in command_of(state)


def test_charm_leaves_active_when_the_container_becomes_unreachable(
    context: Context, base_state: State
):
    # GIVEN an active charm
    state = context.run(context.on.config_changed(), base_state)
    assert isinstance(state.unit_status, ActiveStatus)

    # WHEN the workload container goes away and config changes
    container = dataclasses.replace(state.get_container(CONTAINER_NAME), can_connect=False)
    state = dataclasses.replace(
        state,
        containers=[container],
        config={**state.config, "templates_file": "doesn't matter"},
    )
    state = context.run(context.on.config_changed(), state)

    # THEN the charm is no longer active
    assert not isinstance(state.unit_status, ActiveStatus)


def test_charm_blocks_when_started_with_an_invalid_config(context: Context, base_state: State):
    """Alertmanager exits on an invalid config, so the charm must block instead of crash-looping."""
    # GIVEN a config that declares a "templates" section
    state_in = dataclasses.replace(base_state, config={"config_file": "templates: [wrong]"})

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the charm blocks
    assert isinstance(state.unit_status, BlockedStatus)


def test_charm_blocks_when_a_valid_config_is_replaced_with_an_invalid_one(
    context: Context, base_state: State
):
    # GIVEN an active charm with a valid config
    state_in = dataclasses.replace(base_state, config={"config_file": "templates: []"})
    state = context.run(context.on.config_changed(), state_in)
    assert isinstance(state.unit_status, ActiveStatus)

    # WHEN the config is updated to an invalid one
    state = dataclasses.replace(state, config={"config_file": "templates: [wrong]"})
    state = context.run(context.on.config_changed(), state)

    # THEN the charm blocks
    assert isinstance(state.unit_status, BlockedStatus)

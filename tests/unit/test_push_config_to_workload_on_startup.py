#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test: Push config to workload on startup."""

import dataclasses
import logging

import pytest
import validators
import yaml
from helpers import begin_with_initial_hooks_isolated
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Container, Context, Exec, PeerRelation, State

logger = logging.getLogger(__name__)

CONTAINER_NAME = "alertmanager"
CONFIG_PATH = "/etc/alertmanager/alertmanager.yml"
AMTOOL_CONFIG_PATH = "/etc/amtool/config.yml"


def make_container(can_connect: bool = True, files: dict | None = None) -> Container:
    """Create the alertmanager container with necessary execs."""
    return Container(
        CONTAINER_NAME,
        can_connect=can_connect,
        execs={
            Exec(["update-ca-certificates", "--fresh"]),
            Exec(
                ["alertmanager", "--version"],
                stdout="alertmanager, version 0.23.0 (branch: HEAD, ...)",
            ),
            Exec(["/usr/bin/amtool", "check-config", CONFIG_PATH]),
        },
        **({} if files is None else {"files": files}),
    )


@pytest.fixture
def peer_relation() -> PeerRelation:
    return PeerRelation("replicas")


class TestPushConfigToWorkloadOnStartup:
    """Feature: Push config to workload on startup.

    Background: Charm starts up with initial hooks.
    """

    @pytest.fixture
    def state_after_startup(self, context: Context) -> State:
        """Run initial hooks and return state after startup."""
        return begin_with_initial_hooks_isolated(context)

    @pytest.mark.parametrize("is_leader", [True, False])
    def test_single_unit_cluster(self, context: Context, is_leader: bool):
        """Scenario: Current unit is the only unit present."""
        state = begin_with_initial_hooks_isolated(context, leader=is_leader)

        # Get the container from the resulting state
        container = state.get_container(CONTAINER_NAME)

        # THEN amtool config is rendered
        amtool_config_file = container.get_filesystem(context).joinpath(
            AMTOOL_CONFIG_PATH.lstrip("/")
        )
        assert amtool_config_file.exists(), "amtool config should be written"
        amtool_config = yaml.safe_load(amtool_config_file.read_text())
        assert validators.url(amtool_config["alertmanager.url"], simple_host=True)

        # AND alertmanager config is rendered
        am_config_file = container.get_filesystem(context).joinpath(CONFIG_PATH.lstrip("/"))
        assert am_config_file.exists(), "alertmanager config should be written"
        am_config = yaml.safe_load(am_config_file.read_text())
        assert set(am_config.keys()) >= {"global", "route", "receivers"}

        # AND path to config file is part of pebble layer command
        plan = container.plan
        command = plan.services["alertmanager"].command
        assert f"--config.file={CONFIG_PATH}" in command

        # AND peer clusters cli arg is not present in pebble layer command
        assert "--cluster.peer=" not in command

    @pytest.mark.skip("https://github.com/canonical/operator/issues/736")
    def test_multi_unit_cluster(self, context: Context, peer_relation: PeerRelation):
        """Scenario: Current unit is a part of a multi-unit cluster."""
        # GIVEN multiple units are present
        num_units = 3
        peer_units_data = {i: {"private_address": f"http://fqdn-{i}"} for i in range(1, num_units)}
        peer_rel = dataclasses.replace(peer_relation, peers_data=peer_units_data)

        container = make_container()
        state = State(
            leader=False,
            config={"config_file": ""},
            containers=[container],
            relations=[peer_rel],
        )

        state = context.run(context.on.pebble_ready(container), state)

        # THEN peer clusters cli arg is present in pebble layer command
        container = state.get_container(CONTAINER_NAME)
        command = container.plan.services["alertmanager"].command
        assert "--cluster.peer=" in command

    def test_charm_blocks_on_connection_error(self, context: Context, state_after_startup: State):
        """Test charm goes to waiting status when container connection is lost."""
        assert state_after_startup.unit_status == ActiveStatus()

        # Simulate losing connection to container
        container = state_after_startup.get_container(CONTAINER_NAME)
        disconnected_container = dataclasses.replace(container, can_connect=False)
        state = dataclasses.replace(
            state_after_startup,
            containers=[disconnected_container],
            config={"config_file": "", "templates_file": "doesn't matter"},
        )

        state = context.run(context.on.config_changed(), state)
        assert state.unit_status != ActiveStatus()


class TestInvalidConfig:
    """Feature: Charm must block when invalid config is provided.

    Background: alertmanager exits when config is invalid, so this must be guarded against,
    otherwise pebble will keep trying to restart it, resulting in an idle crash-loop.
    """

    def test_charm_blocks_on_invalid_config_on_startup(self, context: Context):
        """Test charm blocks when started with invalid config."""
        from unittest.mock import patch

        # Mock check_config to return an error for invalid config
        def check_config_invalid(self, config_yaml):
            if "templates: [wrong]" in config_yaml or "[wrong]" in str(config_yaml):
                return ("", "invalid config: wrong templates")
            return ("0.0.0", "")

        from alertmanager import WorkloadManager

        with patch.object(WorkloadManager, "check_config", check_config_invalid):
            container = make_container()
            state = State(
                config={"config_file": "templates: [wrong]"},
                containers=[container],
            )

            # Run through initial hooks
            state = context.run(context.on.install(), state)

            peer_rel = PeerRelation("replicas")
            state = dataclasses.replace(state, relations=[peer_rel], leader=True)
            state = context.run(context.on.relation_created(peer_rel), state)
            state = context.run(context.on.leader_elected(), state)
            state = context.run(context.on.config_changed(), state)

            container = dataclasses.replace(container, can_connect=True)
            state = dataclasses.replace(state, containers=[container])
            state = context.run(context.on.pebble_ready(container), state)

            # THEN the charm goes into blocked status
            assert isinstance(state.unit_status, BlockedStatus)

    def test_charm_blocks_on_invalid_config_changed(self, context: Context):
        """Test charm blocks when config changes to invalid."""
        from unittest.mock import patch

        from alertmanager import WorkloadManager

        # Start with valid config
        state = begin_with_initial_hooks_isolated(context)
        assert isinstance(state.unit_status, ActiveStatus)

        # Now mock check_config to fail for invalid config
        def check_config_invalid(self, config_yaml):
            if "templates: [wrong]" in config_yaml or "[wrong]" in str(config_yaml):
                return ("", "invalid config: wrong templates")
            return ("0.0.0", "")

        with patch.object(WorkloadManager, "check_config", check_config_invalid):
            # Update to invalid config
            state = dataclasses.replace(
                state,
                config={"config_file": "templates: [wrong]"},
            )
            state = context.run(context.on.config_changed(), state)

            # THEN the charm goes into blocked status
            assert isinstance(state.unit_status, BlockedStatus)

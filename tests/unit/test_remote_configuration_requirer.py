# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the RemoteConfigurationRequirer using Scenario with the real AlertmanagerCharm."""

import dataclasses
import json
import logging
from typing import cast

import pytest
import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import DEFAULT_RELATION_NAME
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import begin_with_initial_hooks_isolated
from ops.model import BlockedStatus
from ops.testing import Context, Relation, State

logger = logging.getLogger(__name__)

TEST_ALERTMANAGER_CONFIG_FILE = "/test/rules/dir/config_file.yml"
TEST_ALERTMANAGER_DEFAULT_CONFIG = """route:
  receiver: placeholder
receivers:
- name: placeholder
"""
TEST_ALERTMANAGER_REMOTE_CONFIG = """receivers:
- name: test_receiver
route:
  receiver: test_receiver
  group_by:
  - alertname
  group_wait: 1234s
  group_interval: 4321s
  repeat_interval: 1111h
"""

CONFIG_PATH = "/etc/alertmanager/alertmanager.yml"
TEMPLATES_PATH = "/etc/alertmanager/templates.tmpl"


def make_remote_config_relation(
    rel_id: int = 20,
    alertmanager_config: dict | None = None,
    alertmanager_templates: list[str] | None = None,
) -> Relation:
    """Create a remote configuration relation with provider data."""
    remote_app_data = {}
    if alertmanager_config is not None:
        remote_app_data["alertmanager_config"] = json.dumps(alertmanager_config)
    if alertmanager_templates is not None:
        remote_app_data["alertmanager_templates"] = json.dumps(alertmanager_templates)

    return Relation(
        DEFAULT_RELATION_NAME,
        id=rel_id,
        remote_app_name="remote-config-provider",
        remote_app_data=remote_app_data,
        remote_units_data={0: {}},
    )


class TestAlertmanagerRemoteConfigurationRequirer:
    """Tests for the RemoteConfigurationRequirer with AlertmanagerCharm."""

    @pytest.fixture
    def initial_state(self, context: Context) -> State:
        """Get state after initial hooks."""
        return begin_with_initial_hooks_isolated(context)

    def test_valid_config_pushed_to_relation_data_bag_updates_alertmanager_config(
        self, context: Context, initial_state: State
    ):
        """Test that valid remote config updates the alertmanager config."""
        remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)

        # Expected config includes juju topology in group_by
        expected_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        route = cast(dict, expected_config.get("route", {}))
        route["group_by"] = list(
            set(route.get("group_by", [])).union(
                ["juju_application", "juju_model", "juju_model_uuid"]
            )
        )
        expected_config["route"] = route

        # Add remote config relation
        remote_config_rel = make_remote_config_relation(alertmanager_config=remote_config)
        state = dataclasses.replace(
            initial_state, relations=[*initial_state.relations, remote_config_rel]
        )
        state = context.run(context.on.relation_changed(remote_config_rel), state)

        # Verify the config was written to the container
        container = state.get_container("alertmanager")
        config_file = container.get_filesystem(context).joinpath(CONFIG_PATH.lstrip("/"))
        assert config_file.exists()

        actual_config = yaml.safe_load(config_file.read_text())
        assert DeepDiff(actual_config, expected_config, ignore_order=True) == {}

    def test_configs_available_from_both_relation_data_bag_and_charm_config_block_charm(
        self, context: Context, initial_state: State
    ):
        """Test that having both remote and charm config blocks the charm."""
        remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)

        # Add remote config relation first
        remote_config_rel = make_remote_config_relation(alertmanager_config=remote_config)
        state = dataclasses.replace(
            initial_state, relations=[*initial_state.relations, remote_config_rel]
        )
        state = context.run(context.on.relation_changed(remote_config_rel), state)

        # Now also set charm config
        state = dataclasses.replace(
            state, config={"config_file": TEST_ALERTMANAGER_DEFAULT_CONFIG}
        )
        state = context.run(context.on.config_changed(), state)

        # Charm should be blocked
        assert state.unit_status == BlockedStatus("Multiple configs detected")

    def test_invalid_config_pushed_to_the_relation_data_bag_does_not_update_alertmanager_config(
        self, context: Context, initial_state: State
    ):
        """Test that invalid remote config doesn't update alertmanager config."""
        invalid_config = yaml.safe_load("some: invalid_config")

        # Get initial config
        container = initial_state.get_container("alertmanager")
        config_file_initial = container.get_filesystem(context).joinpath(CONFIG_PATH.lstrip("/"))
        initial_config = (
            yaml.safe_load(config_file_initial.read_text()) if config_file_initial.exists() else {}
        )

        # Add remote config relation with invalid config
        remote_config_rel = make_remote_config_relation(alertmanager_config=invalid_config)
        state = dataclasses.replace(
            initial_state, relations=[*initial_state.relations, remote_config_rel]
        )
        state = context.run(context.on.relation_changed(remote_config_rel), state)

        # Verify the invalid config wasn't applied
        container = state.get_container("alertmanager")
        config_file = container.get_filesystem(context).joinpath(CONFIG_PATH.lstrip("/"))
        assert config_file.exists()

        actual_config = yaml.safe_load(config_file.read_text())
        assert "invalid_config" not in actual_config

    def test_templates_pushed_to_relation_data_bag_are_saved_to_templates_file_in_alertmanager(
        self, context: Context, initial_state: State
    ):
        """Test that templates from relation data are saved to the templates file."""
        remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        test_template = '{{define "myTemplate"}}do something{{end}}'

        # Add remote config relation with templates
        remote_config_rel = make_remote_config_relation(
            alertmanager_config=remote_config,
            alertmanager_templates=[test_template],
        )
        state = dataclasses.replace(
            initial_state, relations=[*initial_state.relations, remote_config_rel]
        )
        state = context.run(context.on.relation_changed(remote_config_rel), state)

        # Verify the templates were written to the container
        container = state.get_container("alertmanager")
        templates_file = container.get_filesystem(context).joinpath(TEMPLATES_PATH.lstrip("/"))
        assert templates_file.exists()
        assert templates_file.read_text() == test_template

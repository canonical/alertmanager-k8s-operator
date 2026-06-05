# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the RemoteConfigurationProvider library using Scenario."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
    ConfigReadError,
    RemoteConfigurationProvider,
)
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource
from ops.testing import Context, PeerRelation, Relation, State

logger = logging.getLogger(__name__)

TEST_APP_NAME = "provider-tester"
TEST_CONFIG_DIR = Path(__file__).parent / "test_config"
TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH = TEST_CONFIG_DIR / "alertmanager.yml"
TEST_ALERTMANAGER_CONFIG_WITH_TEMPLATES_FILE_PATH = (
    TEST_CONFIG_DIR / "alertmanager_with_templates.yml"
)
TEST_ALERTMANAGER_INVALID_CONFIG_FILE_PATH = TEST_CONFIG_DIR / "alertmanager_invalid.yml"
TEST_ALERTMANAGER_TEMPLATES_FILE_PATH = TEST_CONFIG_DIR / "test_templates.tmpl"
TEST_ALERTMANAGER_EMPTY_CONFIG_FILE_PATH = TEST_CONFIG_DIR / "alertmanager_empty.yml"

PROVIDER_METADATA = {
    "name": TEST_APP_NAME,
    "provides": {
        DEFAULT_RELATION_NAME: {"interface": "alertmanager_remote_configuration"},
    },
    "peers": {
        "replicas": {"interface": "provider_replica"},
    },
}


class AlertmanagerConfigFileChangedEvent(EventBase):
    pass


class AlertmanagerConfigFileChangedCharmEvents(CharmEvents):
    alertmanager_config_file_changed = EventSource(AlertmanagerConfigFileChangedEvent)


class RemoteConfigurationProviderCharm(CharmBase):
    """Test charm that uses the RemoteConfigurationProvider library."""

    ALERTMANAGER_CONFIG_FILE: Path = TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH

    on = AlertmanagerConfigFileChangedCharmEvents()  # pyright: ignore

    def __init__(self, *args):
        super().__init__(*args)

        # Track configuration_broken events via peer relation data
        self._peer_relation_name = "replicas"

        alertmanager_config = RemoteConfigurationProvider.load_config_file(
            str(self.ALERTMANAGER_CONFIG_FILE)
        )
        self.remote_configuration_provider = RemoteConfigurationProvider(
            charm=self,
            alertmanager_config=alertmanager_config,
            relation_name=DEFAULT_RELATION_NAME,
        )

        self.framework.observe(
            self.remote_configuration_provider.on.configuration_broken,
            self._on_configuration_broken,
        )
        # Also observe relation_changed to update config
        self.framework.observe(
            self.on[DEFAULT_RELATION_NAME].relation_changed, self._on_relation_changed
        )

    def _on_relation_changed(self, _):
        """Update config when relation changes (used to trigger config reload in tests)."""
        try:
            alertmanager_config = RemoteConfigurationProvider.load_config_file(
                str(self.ALERTMANAGER_CONFIG_FILE)
            )
            self.remote_configuration_provider.update_relation_data_bag(alertmanager_config)
        except ConfigReadError:
            logger.warning("Error reading Alertmanager config file.")

    def _on_configuration_broken(self, _):
        if peer := self.model.get_relation(self._peer_relation_name):
            count = int(peer.data[self.unit].get("configuration_broken_count", "0"))
            peer.data[self.unit]["configuration_broken_count"] = str(count + 1)


@pytest.fixture
def provider_context():
    """Create a Context for the provider charm."""
    return Context(charm_type=RemoteConfigurationProviderCharm, meta=PROVIDER_METADATA)


def get_configuration_broken_count(state: State) -> int:
    """Extract the configuration_broken event count from peer relation data."""
    peers = state.get_relations("replicas")
    if not peers:
        return 0
    return int(peers[0].local_unit_data.get("configuration_broken_count", "0"))


class TestAlertmanagerRemoteConfigurationProvider:
    """Tests for the RemoteConfigurationProvider library."""

    def test_config_without_templates_updates_only_alertmanager_config_in_the_data_bag(
        self, provider_context: Context
    ):
        """Test that config without templates only updates alertmanager_config."""
        expected_config = yaml.safe_load(
            TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH.read_text()
        )

        # Create relation and run relation_joined
        remote_config_rel = Relation(
            DEFAULT_RELATION_NAME,
            id=10,
            remote_app_name="requirer",
            remote_units_data={0: {}},
        )
        state = State(leader=True, relations=[remote_config_rel])
        state = provider_context.run(
            provider_context.on.relation_joined(remote_config_rel, remote_unit=0), state
        )

        # Check relation data
        rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
        assert json.loads(rel.local_app_data["alertmanager_config"]) == expected_config
        assert json.loads(rel.local_app_data["alertmanager_templates"]) == []

    def test_config_with_templates_updates_both_in_the_data_bag(self, provider_context: Context):
        """Test that config with templates updates both config and templates."""
        expected_templates = TEST_ALERTMANAGER_TEMPLATES_FILE_PATH.read_text().splitlines(
            keepends=True
        )

        # Patch the config file path before charm init
        with patch.object(
            RemoteConfigurationProviderCharm,
            "ALERTMANAGER_CONFIG_FILE",
            TEST_ALERTMANAGER_CONFIG_WITH_TEMPLATES_FILE_PATH,
        ):
            # Create relation
            remote_config_rel = Relation(
                DEFAULT_RELATION_NAME,
                id=10,
                remote_app_name="requirer",
                remote_units_data={0: {}},
            )
            state = State(leader=True, relations=[remote_config_rel])
            # relation_joined triggers the config load and data bag update
            state = provider_context.run(
                provider_context.on.relation_joined(remote_config_rel, remote_unit=0), state
            )

            # Check templates in relation data
            rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
            assert json.loads(rel.local_app_data["alertmanager_templates"]) == expected_templates

    def test_invalid_config_emits_remote_configuration_broken_event(
        self, provider_context: Context
    ):
        """Test that invalid config emits configuration_broken event."""
        # Add peer relation to track events
        peer_rel = PeerRelation("replicas", id=0)
        remote_config_rel = Relation(
            DEFAULT_RELATION_NAME,
            id=10,
            remote_app_name="requirer",
            remote_units_data={0: {}},
        )

        # Start with valid config
        state = State(leader=True, relations=[peer_rel, remote_config_rel])
        state = provider_context.run(
            provider_context.on.relation_joined(remote_config_rel, remote_unit=0), state
        )

        initial_count = get_configuration_broken_count(state)

        # Now change to invalid config and trigger relation_changed
        with patch.object(
            RemoteConfigurationProviderCharm,
            "ALERTMANAGER_CONFIG_FILE",
            TEST_ALERTMANAGER_INVALID_CONFIG_FILE_PATH,
        ):
            rel_from_state = state.get_relations(DEFAULT_RELATION_NAME)[0]
            state = provider_context.run(
                provider_context.on.relation_changed(rel_from_state), state
            )

        assert get_configuration_broken_count(state) > initial_count

    def test_invalid_config_clears_relation_data_bag(self, provider_context: Context):
        """Test that invalid config clears the relation data bag."""
        # Start with valid config
        remote_config_rel = Relation(
            DEFAULT_RELATION_NAME,
            id=10,
            remote_app_name="requirer",
            remote_units_data={0: {}},
        )
        state = State(leader=True, relations=[remote_config_rel])
        state = provider_context.run(
            provider_context.on.relation_joined(remote_config_rel, remote_unit=0), state
        )

        # Verify config was set
        rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
        assert "alertmanager_config" in rel.local_app_data

        # Now change to invalid config and trigger relation_changed
        with patch.object(
            RemoteConfigurationProviderCharm,
            "ALERTMANAGER_CONFIG_FILE",
            TEST_ALERTMANAGER_INVALID_CONFIG_FILE_PATH,
        ):
            rel_from_state = state.get_relations(DEFAULT_RELATION_NAME)[0]
            state = provider_context.run(
                provider_context.on.relation_changed(rel_from_state), state
            )

        # Config should be cleared
        rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
        assert "alertmanager_config" not in rel.local_app_data

    def test_empty_config_file_clears_relation_data_bag(self, provider_context: Context):
        """Test that empty config file clears the relation data bag."""
        # Start with valid config
        remote_config_rel = Relation(
            DEFAULT_RELATION_NAME,
            id=10,
            remote_app_name="requirer",
            remote_units_data={0: {}},
        )
        state = State(leader=True, relations=[remote_config_rel])
        state = provider_context.run(
            provider_context.on.relation_joined(remote_config_rel, remote_unit=0), state
        )

        # Verify config was set
        rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
        assert "alertmanager_config" in rel.local_app_data

        # Now change to empty config and trigger relation_changed
        with patch.object(
            RemoteConfigurationProviderCharm,
            "ALERTMANAGER_CONFIG_FILE",
            TEST_ALERTMANAGER_EMPTY_CONFIG_FILE_PATH,
        ):
            rel_from_state = state.get_relations(DEFAULT_RELATION_NAME)[0]
            state = provider_context.run(
                provider_context.on.relation_changed(rel_from_state), state
            )

        # Config should be cleared
        rel = state.get_relations(DEFAULT_RELATION_NAME)[0]
        assert "alertmanager_config" not in rel.local_app_data

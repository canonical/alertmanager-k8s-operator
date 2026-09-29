# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: a provider charm publishes an alertmanager config read from a file on disk."""

import json
import logging
from unittest.mock import patch

import pytest
import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
    AlertmanagerConfigurationBrokenEvent,
    ConfigReadError,
    RemoteConfigurationProvider,
)
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource
from ops.testing import Context, Relation, State

logger = logging.getLogger(__name__)

METADATA = {
    "name": "provider-tester",
    "provides": {DEFAULT_RELATION_NAME: {"interface": "alertmanager_remote_configuration"}},
}
CONFIG_WITHOUT_TEMPLATES = "./tests/unit/test_config/alertmanager.yml"
CONFIG_WITH_TEMPLATES = "./tests/unit/test_config/alertmanager_with_templates.yml"
INVALID_CONFIG = "./tests/unit/test_config/alertmanager_invalid.yml"
EMPTY_CONFIG = "./tests/unit/test_config/alertmanager_empty.yml"
TEMPLATES_FILE = "./tests/unit/test_config/test_templates.tmpl"


class AlertmanagerConfigFileChangedEvent(EventBase):
    pass


class AlertmanagerConfigFileChangedCharmEvents(CharmEvents):
    alertmanager_config_file_changed = EventSource(AlertmanagerConfigFileChangedEvent)


class RemoteConfigurationProviderCharm(CharmBase):
    ALERTMANAGER_CONFIG_FILE = CONFIG_WITHOUT_TEMPLATES

    on = AlertmanagerConfigFileChangedCharmEvents()  # pyright: ignore

    def __init__(self, *args):
        super().__init__(*args)

        alertmanager_config = RemoteConfigurationProvider.load_config_file(
            self.ALERTMANAGER_CONFIG_FILE
        )
        self.remote_configuration_provider = RemoteConfigurationProvider(
            charm=self,
            alertmanager_config=alertmanager_config,
            relation_name=DEFAULT_RELATION_NAME,
        )

        self.framework.observe(self.on.alertmanager_config_file_changed, self._update_config)

    def _update_config(self, _):
        try:
            alertmanager_config = RemoteConfigurationProvider.load_config_file(
                self.ALERTMANAGER_CONFIG_FILE
            )
            self.remote_configuration_provider.update_relation_data_bag(alertmanager_config)
        except ConfigReadError:
            logger.warning("Error reading Alertmanager config file.")


@pytest.fixture
def context() -> Context:
    return Context(RemoteConfigurationProviderCharm, meta=METADATA)


@pytest.fixture
def relation() -> Relation:
    return Relation(DEFAULT_RELATION_NAME, remote_app_name="requirer")


@pytest.fixture
def joined(context: Context, relation) -> State:
    """A leader provider with a requirer that has just joined the relation."""
    return context.run(
        context.on.relation_joined(relation, remote_unit=0),
        State(leader=True, relations=[relation]),
    )


def reload_config_from(context: Context, state: State, config_file: str) -> State:
    """Point the charm at a different config file and let it republish."""
    with patch.object(
        RemoteConfigurationProviderCharm, "ALERTMANAGER_CONFIG_FILE", config_file
    ):
        with context(context.on.update_status(), state) as mgr:
            mgr.charm.on.alertmanager_config_file_changed.emit()
            return mgr.run()


def published(state: State) -> dict:
    return dict(state.get_relations(DEFAULT_RELATION_NAME)[0].local_app_data)


def test_a_config_without_templates_is_published_with_an_empty_template_list(joined: State):
    # GIVEN a provider whose config file declares no templates
    # WHEN a requirer joins
    # THEN the config is published verbatim
    with open(CONFIG_WITHOUT_TEMPLATES, "r") as config_yaml:
        expected_config = yaml.safe_load(config_yaml)

    data = published(joined)
    assert json.loads(data["alertmanager_config"]) == expected_config

    # AND the templates are published as an empty list
    assert json.loads(data["alertmanager_templates"]) == []


def test_templates_are_published_alongside_the_config(context: Context, joined: State):
    # GIVEN a provider with a requirer already related
    # WHEN its config file is swapped for one that declares templates
    state = reload_config_from(context, joined, CONFIG_WITH_TEMPLATES)

    # THEN the templates' contents are published
    with open(TEMPLATES_FILE, "r") as templates_file:
        expected_templates = templates_file.readlines()

    assert json.loads(published(state)["alertmanager_templates"]) == expected_templates


def test_an_invalid_config_reports_the_configuration_as_broken(context: Context, joined: State):
    # GIVEN a provider with a requirer already related
    # WHEN its config file is swapped for an invalid one
    reload_config_from(context, joined, INVALID_CONFIG)

    # THEN the provider reports the configuration as broken
    assert any(
        isinstance(event, AlertmanagerConfigurationBrokenEvent)
        for event in context.emitted_events
    )


@pytest.mark.parametrize(
    "config_file", [pytest.param(INVALID_CONFIG, id="invalid"), pytest.param(EMPTY_CONFIG, id="empty")]
)
def test_an_unusable_config_is_withdrawn_from_the_relation(
    context: Context, joined: State, config_file: str
):
    # GIVEN a provider that has published a valid config
    assert "alertmanager_config" in published(joined)

    # WHEN its config file is swapped for an unusable one
    state = reload_config_from(context, joined, config_file)

    # THEN the stale config is withdrawn rather than left to be consumed
    assert "alertmanager_config" not in published(state)

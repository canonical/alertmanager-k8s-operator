# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
    ConfigReadError,
    RemoteConfigurationProvider,
)
from ops import testing
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource

logger = logging.getLogger(__name__)

testing.SIMULATE_CAN_CONNECT = True

TEST_APP_NAME = "provider-tester"
METADATA = f"""
name: {TEST_APP_NAME}
provides:
  {DEFAULT_RELATION_NAME}:
    interface: alertmanager_remote_configuration
"""
TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH = "./tests/unit/test_config/alertmanager.yml"
TEST_ALERTMANAGER_CONFIG_WITH_TEMPLATES_FILE_PATH = (
    "./tests/unit/test_config/alertmanager_with_templates.yml"
)
TEST_ALERTMANAGER_INVALID_CONFIG_FILE_PATH = "./tests/unit/test_config/alertmanager_invalid.yml"
TEST_ALERTMANAGER_TEMPLATES_FILE_PATH = "./tests/unit/test_config/test_templates.tmpl"


class AlertmanagerConfigFileChangedEvent(EventBase):
    pass


class AlertmanagerConfigFileChangedCharmEvents(CharmEvents):
    alertmanager_config_file_changed = EventSource(AlertmanagerConfigFileChangedEvent)


class RemoteConfigurationProviderCharm(CharmBase):
    ALERTMANAGER_CONFIG_FILE = TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH

    on = AlertmanagerConfigFileChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)

        alertmanager_config = RemoteConfigurationProvider.load_config_file(
            Path(self.ALERTMANAGER_CONFIG_FILE)
        )
        self.remote_configuration_provider = RemoteConfigurationProvider(
            charm=self,
            alertmanager_config=alertmanager_config,
            relation_name=DEFAULT_RELATION_NAME,
        )

        self.framework.observe(self.on.alertmanager_config_file_changed, self._update_config)

    def _update_config(self, _):
        try:
            relation = self.model.get_relation(DEFAULT_RELATION_NAME)
            alertmanager_config = RemoteConfigurationProvider.load_config_file(
                Path(self.ALERTMANAGER_CONFIG_FILE)
            )
            self.remote_configuration_provider.update_relation_data_bag(
                alertmanager_config, relation
            )
        except ConfigReadError:
            logger.warning("Error reading Alertmanager config file.")


class TestAlertmanagerRemoteConfigurationProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = testing.Harness(RemoteConfigurationProviderCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def test_config_without_templates_updates_only_alertmanager_config_in_the_data_bag(self):
        with open(TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)

        relation_id = self.harness.add_relation(DEFAULT_RELATION_NAME, "requirer")
        self.harness.add_relation_unit(relation_id, "requirer/0")

        self.assertEqual(
            json.loads(
                self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"]
            ),
            expected_config,
        )
        self.assertEqual(
            json.loads(
                self.harness.get_relation_data(relation_id, TEST_APP_NAME)[
                    "alertmanager_templates"
                ]
            ),
            [],
        )

    @patch(
        "test_remote_configuration_provider.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",  # noqa: E501
        new_callable=PropertyMock,
    )
    def test_config_with_templates_updates_both_alertmanager_config_and_alertmanager_templates_in_the_data_bag(  # noqa: E501
        self, patched_alertmanager_config_file
    ):
        patched_alertmanager_config_file.return_value = (
            TEST_ALERTMANAGER_CONFIG_WITH_TEMPLATES_FILE_PATH
        )
        with open(TEST_ALERTMANAGER_TEMPLATES_FILE_PATH, "r") as templates_file:
            expected_templates = templates_file.readlines()
        relation_id = self.harness.add_relation(DEFAULT_RELATION_NAME, "requirer")
        self.harness.add_relation_unit(relation_id, "requirer/0")

        self.harness.charm.on.alertmanager_config_file_changed.emit()

        self.assertEqual(
            json.loads(
                self.harness.get_relation_data(relation_id, TEST_APP_NAME)[
                    "alertmanager_templates"
                ]
            ),
            expected_templates,
        )

    @patch(
        "test_remote_configuration_provider.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",  # noqa: E501
        new_callable=PropertyMock,
    )
    def test_invalid_config_does_not_update_the_data_bag(self, patched_alertmanager_config_file):
        patched_alertmanager_config_file.return_value = TEST_ALERTMANAGER_INVALID_CONFIG_FILE_PATH
        with open(TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)
        relation_id = self.harness.add_relation(DEFAULT_RELATION_NAME, "requirer")
        self.harness.add_relation_unit(relation_id, "requirer/0")

        self.harness.charm.on.alertmanager_config_file_changed.emit()

        self.assertEqual(
            json.loads(
                self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"]
            ),
            expected_config,
        )

    @patch(
        "test_remote_configuration_provider.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",  # noqa: E501
        new_callable=PropertyMock,
    )
    def test_empty_config_file_does_not_update_relation_data_bag(
        self, patched_alertmanager_config_file
    ):
        test_config_file = "./tests/unit/test_config/alertmanager_empty.yml"
        patched_alertmanager_config_file.return_value = test_config_file
        with open(TEST_ALERTMANAGER_CONFIG_WITHOUT_TEMPLATES_FILE_PATH, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)
        relation_id = self.harness.add_relation(DEFAULT_RELATION_NAME, "requirer")
        self.harness.add_relation_unit(relation_id, "requirer/0")

        self.harness.charm.on.alertmanager_config_file_changed.emit()

        self.assertEqual(
            json.loads(
                self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"]
            ),
            expected_config,
        )

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import unittest
from typing import cast
from unittest.mock import Mock, PropertyMock, call, patch

import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
    ConfigReadError,
    RemoteConfigurationProvider,
    load_config_file,
)
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import k8s_resource_multipatch
from ops import testing
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource
from ops.model import BlockedStatus

from charm import AlertmanagerCharm

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

        alertmanager_config = load_config_file(self.ALERTMANAGER_CONFIG_FILE)
        self.remote_configuration_provider = RemoteConfigurationProvider(
            charm=self,
            alertmanager_config=alertmanager_config,
            relation_name=DEFAULT_RELATION_NAME,
        )

        self.framework.observe(self.on.alertmanager_config_file_changed, self._update_config)

    def _update_config(self, _):
        try:
            relation = self.model.get_relation(DEFAULT_RELATION_NAME)
            alertmanager_config = load_config_file(self.ALERTMANAGER_CONFIG_FILE)
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
        "test_remote_configuration.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",
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
        "test_remote_configuration.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",
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
        "test_remote_configuration.RemoteConfigurationProviderCharm.ALERTMANAGER_CONFIG_FILE",
        new_callable=PropertyMock,
    )
    def test_non_existent_config_file_does_not_update_relation_data_bag(
        self, patched_alertmanager_config_file
    ):
        test_config_file = "/i/do/not/exist.yml"
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


TEST_ALERTMANAGER_CONFIG_FILE = "/test/rules/dir/config_file.yml"
TEST_ALERTMANAGER_DEFAULT_CONFIG = """route:
  receiver: dummy
receivers:
- name: dummy
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


class TestAlertmanagerRemoteConfigurationRequirer(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    def setUp(self, _) -> None:
        self.harness = testing.Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.set_can_connect("alertmanager", True)
        self.harness.begin_with_initial_hooks()

        self.relation_id = self.harness.add_relation(
            DEFAULT_RELATION_NAME, "remote-config-provider"
        )
        self.harness.add_relation_unit(self.relation_id, "remote-config-provider/0")

    @patch("ops.model.Container.push")
    @patch("ops.model.Container.exec")
    @patch("charm.AlertmanagerCharm._config_path", new_callable=PropertyMock)
    @k8s_resource_multipatch
    def test_valid_config_pushed_to_relation_data_bag_updates_alertmanager_config(
        self, patched_config_path, patched_exec, patched_push
    ):
        patched_config_path.return_value = TEST_ALERTMANAGER_CONFIG_FILE
        patched_exec_mock = Mock()
        patched_exec_mock.wait_output.return_value = ("whatever", "")
        patched_exec.return_value = patched_exec_mock
        expected_config = remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        # add juju topology to "group_by"
        route = cast(dict, expected_config.get("route", {}))
        route["group_by"] = list(
            set(route.get("group_by", [])).union(
                ["juju_application", "juju_model", "juju_model_uuid"]
            )
        )
        expected_config["route"] = route

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={"alertmanager_config": json.dumps(remote_config)},
        )

        for mock_call in patched_push.mock_calls:
            for item in mock_call:
                if TEST_ALERTMANAGER_CONFIG_FILE in item:
                    self.assertEqual(item[0], TEST_ALERTMANAGER_CONFIG_FILE)
                    self.assertEqual(
                        DeepDiff(yaml.safe_load(item[1]), expected_config, ignore_order=True),
                        {},
                    )

    @k8s_resource_multipatch
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    def test_configs_available_from_both_relation_data_bag_and_charm_config_block_charm(
        self,
    ):
        dummy_remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={"alertmanager_config": json.dumps(dummy_remote_config)},
        )
        self.harness.update_config({"config_file": TEST_ALERTMANAGER_DEFAULT_CONFIG})

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Multiple configs detected")
        )

    @patch("ops.model.Container.push")
    @patch("ops.model.Container.exec")
    @patch("charm.AlertmanagerCharm._default_config", new_callable=PropertyMock)
    @patch("charm.AlertmanagerCharm._config_path", new_callable=PropertyMock)
    @k8s_resource_multipatch
    def test_invalid_config_pushed_to_the_relation_data_bag_does_not_update_alertmanager_config(
        self, patched_config_path, patched_default_config, patched_exec, patched_push
    ):
        patched_config_path.return_value = TEST_ALERTMANAGER_CONFIG_FILE
        patched_exec_mock = Mock()
        patched_exec_mock.wait_output.return_value = ("whatever", "")
        patched_exec.return_value = patched_exec_mock
        default_config = yaml.safe_load(TEST_ALERTMANAGER_DEFAULT_CONFIG)
        patched_default_config.return_value = default_config
        invalid_config = yaml.safe_load("some: invalid_config")

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={"alertmanager_config": json.dumps(invalid_config)},
        )

        for mock_call in patched_push.mock_calls:
            for item in mock_call:
                if TEST_ALERTMANAGER_CONFIG_FILE in item:
                    self.assertEqual(item[0], TEST_ALERTMANAGER_CONFIG_FILE)
                    self.assertEqual(
                        DeepDiff(yaml.safe_load(item[1]), default_config, ignore_order=True),
                        {},
                    )

    @patch("ops.model.Container.push")
    @patch("charm.AlertmanagerCharm._templates_path", new_callable=PropertyMock)
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    @k8s_resource_multipatch
    def test_templates_pushed_to_relation_data_bag_are_saved_to_templates_file_in_alertmanager(
        self, patched_templates_path, patched_push
    ):
        dummy_remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        test_templates_file = "/this/is/test/templates.tmpl"
        patched_templates_path.return_value = test_templates_file
        test_template = '{{define "myTemplate"}}do something{{end}}'
        expected_call = call(test_templates_file, test_template, make_dirs=True)

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={
                "alertmanager_config": json.dumps(dummy_remote_config),
                "alertmanager_templates": json.dumps([test_template])},
        )

        self.assertIn(expected_call, patched_push.mock_calls)

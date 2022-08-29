# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch

import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME as RELATION_NAME,
)
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    ConfigReadError,
    RemoteConfigurationConsumer,
    load_config_file,
)
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import k8s_resource_multipatch
from ops import testing
from ops.charm import CharmBase
from ops.model import BlockedStatus

from charm import AlertmanagerCharm

testing.SIMULATE_CAN_CONNECT = True

TEST_APP_NAME = "consumer-tester"
METADATA = f"""
name: {TEST_APP_NAME}
requires:
  {RELATION_NAME}:
    interface: alertmanager_remote_configuration
    limit: 1
"""
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


class RemoteConfigurationConsumerCharm(CharmBase):
    ALERTMANAGER_CONFIG_FILE = "./tests/unit/test_config/alertmanager.yml"

    def __init__(self, *args):
        super().__init__(*args)

        alertmanager_config = {}
        try:
            alertmanager_config = load_config_file(self.ALERTMANAGER_CONFIG_FILE)
        except ConfigReadError:
            pass
        self.remote_configuration_consumer = RemoteConfigurationConsumer(
            charm=self,
            alertmanager_config=alertmanager_config,
            relation_name=RELATION_NAME,
        )


class TestAlertmanagerRemoteConfigurationConsumer(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = testing.Harness(RemoteConfigurationConsumerCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        testing.SIMULATE_CAN_CONNECT = True
        self.harness.set_leader(True)
        self.harness.begin()

    def test_given_remote_configuration_consumer_charm_providing_config_without_templates_when_relation_joined_then_alertmanager_config_is_updated_in_the_relation_data_bag(  # noqa: E501
        self,
    ):
        test_config_file = "./tests/unit/test_config/alertmanager.yml"
        with open(test_config_file, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)

        relation_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(relation_id, "provider/0")

        self.assertEqual(
            self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"],
            json.dumps(expected_config),
        )

    @patch(
        "test_remote_configuration.RemoteConfigurationConsumerCharm.ALERTMANAGER_CONFIG_FILE",
        new_callable=PropertyMock,
    )
    def test_given_remote_configuration_consumer_charm_providing_config_with_templates_when_relation_joined_then_alertmanager_config_and_alertmanager_templates_are_updated_in_the_relation_data_bag(  # noqa: E501
        self, patched_alertmanager_config_file
    ):
        test_config_file = "./tests/unit/test_config/alertmanager_with_templates.yml"
        test_templates_file = "./tests/unit/test_config/test_templates.tmpl"
        patched_alertmanager_config_file.return_value = test_config_file
        harness = testing.Harness(RemoteConfigurationConsumerCharm, meta=METADATA)
        self.addCleanup(harness.cleanup)
        harness.set_leader(True)
        harness.begin()
        with open(test_config_file, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)
        del expected_config["templates"]
        expected_templates = []
        with open(test_templates_file, "r") as templates_file:
            expected_templates.append(templates_file.read())

        relation_id = harness.add_relation(RELATION_NAME, "provider")
        harness.add_relation_unit(relation_id, "provider/0")

        self.assertEqual(
            harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"],
            json.dumps(expected_config),
        )
        self.assertEqual(
            harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_templates"],
            json.dumps(expected_templates),
        )

    def test_given_remote_configuration_consumer_charm_providing_config_without_templates_when_upgrade_charm_then_alertmanager_config_is_updated_in_the_relation_data_bag(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        test_config_file = "./tests/unit/test_config/alertmanager.yml"
        with open(test_config_file, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)
        relation_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(relation_id, "provider/0")

        self.harness.charm.on.upgrade_charm.emit()

        self.assertEqual(
            self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"],
            json.dumps(expected_config),
        )

    def test_given_remote_configuration_consumer_charm_providing_config_without_templates_when_relation_changed_then_alertmanager_config_is_updated_in_the_relation_data_bag(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        test_config_file = "./tests/unit/test_config/alertmanager.yml"
        with open(test_config_file, "r") as config_yaml:
            expected_config = yaml.safe_load(config_yaml)
        relation_id = self.harness.add_relation(RELATION_NAME, "provider")
        relation = self.harness.model.get_relation(
            relation_name=RELATION_NAME, relation_id=relation_id
        )
        self.harness.add_relation_unit(relation_id, "provider/0")

        self.harness.charm.on.remote_configuration_relation_changed.emit(relation)

        self.assertEqual(
            self.harness.get_relation_data(relation_id, TEST_APP_NAME)["alertmanager_config"],
            json.dumps(expected_config),
        )

    @patch(
        "test_remote_configuration.RemoteConfigurationConsumerCharm.ALERTMANAGER_CONFIG_FILE",
        new_callable=PropertyMock,
    )
    def test_given_remote_configuration_consumer_charm_providing_non_existent_config_file_when_relation_joined_then_relation_data_is_not_set(  # noqa: E501
        self, patched_alertmanager_config_file
    ):
        test_config_file = "/i/do/not/exist.yml"
        patched_alertmanager_config_file.return_value = test_config_file
        harness = testing.Harness(RemoteConfigurationConsumerCharm, meta=METADATA)
        self.addCleanup(harness.cleanup)
        harness.set_leader(True)
        harness.begin()

        relation_id = harness.add_relation(RELATION_NAME, "provider")
        harness.add_relation_unit(relation_id, "provider/0")

        self.assertEqual(harness.get_relation_data(relation_id, TEST_APP_NAME), {})


class TestAlertmanagerRemoteConfigurationProvider(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    def setUp(self, _, patched_urlopen) -> None:
        urllib_response = MagicMock()
        urllib_response.getcode.return_value = 200
        urllib_response.read.return_value = bytes(
            json.dumps({"config": {"original": TEST_ALERTMANAGER_DEFAULT_CONFIG}}),
            encoding="utf-8",
        )
        patched_urlopen.return_value = urllib_response
        self.harness = testing.Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_can_connect("alertmanager", True)
        self.harness.set_leader(True)
        self.harness.begin()

        self.relation_id = self.harness.add_relation(RELATION_NAME, "remote-config-consumer")
        self.harness.add_relation_unit(self.relation_id, "remote-config-consumer")

    def test_given_alertmanager_remote_configuration_relation_not_present_when_remote_configuration_relation_joined_then_current_alertmanager_config_is_pushed_to_the_relation_data_bag(  # noqa: E501
        self,
    ):
        self.assertEqual(
            self.harness.get_relation_data(self.relation_id, self.harness.charm.app.name)[
                "alertmanager_config"
            ],
            json.dumps(TEST_ALERTMANAGER_DEFAULT_CONFIG),
        )

    @patch("ops.model.Container.push")
    @patch("charm.AlertmanagerCharm._config_path", new_callable=PropertyMock)
    def test_given_alertmanager_remote_configurer_provides_alertmanager_configuration_in_the_relation_data_bag_when_remote_configuration_relation_changed_then_config_from_the_relation_data_bag_is_saved_to_alertmanager_config_file(  # noqa: E501
        self, patched_config_path, patched_push
    ):
        patched_config_path.return_value = TEST_ALERTMANAGER_CONFIG_FILE
        remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        expected_config = """receivers:
- name: test_receiver
route:
  group_by:
  - juju_application
  - juju_model
  - alertname
  - juju_model_uuid
  receiver: test_receiver
  group_wait: 1234s
  group_interval: 4321s
  repeat_interval: 1111h
"""

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-consumer",
            key_values={"alertmanager_config": json.dumps(remote_config)},
        )

        for mock_call in patched_push.mock_calls:
            for item in mock_call:
                if TEST_ALERTMANAGER_CONFIG_FILE in item:
                    self.assertEqual(item[0], TEST_ALERTMANAGER_CONFIG_FILE)
                    self.assertEqual(
                        DeepDiff(
                            yaml.safe_load(item[1]),
                            yaml.safe_load(expected_config),
                            ignore_order=True,
                        ),
                        {},
                    )

    @k8s_resource_multipatch
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    def test_given_alertmanager_config_provided_by_both_the_relation_and_the_charm_config_when_remote_configuration_relation_changed_then_charm_goes_to_blocked_status(  # noqa: E501
        self,
    ):
        dummy_charm_config = yaml.safe_load(TEST_ALERTMANAGER_DEFAULT_CONFIG)
        dummy_remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        self.maxDiff = None
        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-consumer",
            key_values={"alertmanager_config": json.dumps(dummy_remote_config)},
        )
        self.harness.update_config({"config_file": dummy_charm_config})

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Multiple configs detected")
        )

    @patch("ops.model.Container.push")
    @patch("charm.AlertmanagerCharm._default_config", new_callable=PropertyMock)
    @patch("charm.AlertmanagerCharm._config_path", new_callable=PropertyMock)
    def test_given_alertmanager_remote_configurer_provides_invalid_alertmanager_configuration_in_the_relation_data_bag_when_remote_configurer_relation_changed_then_invalid_config_is_ignored(  # noqa: E501
        self, patched_config_path, patched_default_config, patched_push
    ):
        patched_config_path.return_value = TEST_ALERTMANAGER_CONFIG_FILE
        default_config = yaml.safe_load(TEST_ALERTMANAGER_DEFAULT_CONFIG)
        patched_default_config.return_value = default_config
        invalid_config = yaml.safe_load("some: invalid_config")

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-consumer",
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
    def test_given_alertmanager_remote_configurer_provides_templates_in_the_relation_data_bag_when_remote_configurer_relation_changed_then_templates_are_saved_to_the_temlpates_file(  # noqa: E501
        self, patched_templates_path, patched_push
    ):
        test_templates_file = "/this/is/test/templates.tmpl"
        patched_templates_path.return_value = test_templates_file
        test_template = '{{define "myTemplate"}}do something{{end}}'
        expected_calls = [call(test_templates_file, test_template, make_dirs=True)]

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-consumer",
            key_values={"alertmanager_templates": json.dumps([test_template])},
        )

        patched_push.assert_has_calls(expected_calls)


def _mock_requests_get(status=200, content="", json_data=None, raise_for_status=None):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    if raise_for_status:
        mock_resp.raise_for_status.side_effect = raise_for_status
    mock_resp.status_code = status
    mock_resp.content = content
    if json_data:
        mock_resp.json = Mock(return_value=json_data)
    return mock_resp

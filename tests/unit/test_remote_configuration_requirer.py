# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import unittest
from typing import cast
from unittest.mock import Mock, patch

import yaml
from charm import AlertmanagerCharm
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
)
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import k8s_resource_multipatch
from ops import testing
from ops.model import BlockedStatus

logger = logging.getLogger(__name__)

testing.SIMULATE_CAN_CONNECT = True

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
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    @k8s_resource_multipatch
    def setUp(self, _) -> None:
        self.harness = testing.Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)

        # TODO: Once we're on ops 2.0.0+ this can be removed as begin_with_initial_hooks()
        # now does it.
        self.harness.set_can_connect("alertmanager", True)

        # In ops 2.0.0+, we need to mock the version, as begin_with_initial_hooks() now triggers
        # pebble-ready, which attempts to obtain the workload version.
        patcher = patch.object(
            AlertmanagerCharm, "_alertmanager_version", property(lambda *_: "0.0.0")
        )
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness.begin_with_initial_hooks()

        self.relation_id = self.harness.add_relation(
            DEFAULT_RELATION_NAME, "remote-config-provider"
        )
        self.harness.add_relation_unit(self.relation_id, "remote-config-provider/0")

    @patch("ops.model.Container.exec")
    @k8s_resource_multipatch
    def test_valid_config_pushed_to_relation_data_bag_updates_alertmanager_config(
        self, patched_exec
    ):
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
        config = self.harness.charm.container.pull(self.harness.charm._config_path)

        self.assertEqual(
            DeepDiff(yaml.safe_load(config.read()), expected_config, ignore_order=True),
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

    @patch("ops.model.Container.exec")
    @patch("config_builder.default_config", yaml.safe_load(TEST_ALERTMANAGER_DEFAULT_CONFIG))
    @k8s_resource_multipatch
    def test_invalid_config_pushed_to_the_relation_data_bag_does_not_update_alertmanager_config(
        self, patched_exec
    ):
        patched_exec_mock = Mock()
        patched_exec_mock.wait_output.return_value = ("whatever", "")
        patched_exec.return_value = patched_exec_mock
        invalid_config = yaml.safe_load("some: invalid_config")

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={"alertmanager_config": json.dumps(invalid_config)},
        )
        config = self.harness.charm.container.pull(self.harness.charm._config_path)

        self.assertNotIn("invalid_config", yaml.safe_load(config.read()))

    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    @k8s_resource_multipatch
    def test_templates_pushed_to_relation_data_bag_are_saved_to_templates_file_in_alertmanager(
        self,
    ):
        dummy_remote_config = yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)
        test_template = '{{define "myTemplate"}}do something{{end}}'

        self.harness.update_relation_data(
            relation_id=self.relation_id,
            app_or_unit="remote-config-provider",
            key_values={
                "alertmanager_config": json.dumps(dummy_remote_config),
                "alertmanager_templates": json.dumps([test_template]),
            },
        )
        updated_templates = self.harness.charm.container.pull(self.harness.charm._templates_path)

        self.assertEqual(updated_templates.read(), test_template)

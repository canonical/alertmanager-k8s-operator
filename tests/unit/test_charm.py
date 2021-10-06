#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import textwrap
import unittest
from unittest.mock import patch

import ops
import yaml
from helpers import PushPullMock, patch_network_get, tautology
from ops.testing import Harness
from ops.model import ActiveStatus, BlockedStatus

from charm import Alertmanager, AlertmanagerCharm

alertmanager_default_config = textwrap.dedent(
    """
            route:
              group_by: ['alertname']
              group_wait: 30s
              group_interval: 5m
              repeat_interval: 1h
              receiver: 'web.hook'
            receivers:
            - name: 'web.hook'
              webhook_configs:
              - url: 'http://127.0.0.1:5001/'
            inhibit_rules:
              - source_match:
                  severity: 'critical'
                target_match:
                  severity: 'warning'
                equal: ['alertname', 'dev', 'instance']
    """
)


@patch_network_get(private_address="1.1.1.1")
@patch.object(Alertmanager, "reload", tautology)
class TestWithInitialHooks(unittest.TestCase):
    container_name: str = "alertmanager"

    @patch.object(AlertmanagerCharm, "_patch_k8s_service", lambda *a, **kw: None)
    @patch("ops.testing._TestingPebbleClient.push")
    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        self.push_pull_mock = PushPullMock()
        self.push_pull_mock.push(AlertmanagerCharm._config_path, alertmanager_default_config)

        self.relation_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        self.harness.set_leader(True)

        network_get_patch = patch_network_get(private_address="1.1.1.1")
        api_get_patch = patch(
            "charm.Alertmanager._get",
            lambda *a, **kw: json.dumps({"versionInfo": {"version": "0.1.2"}}),
        )

        with network_get_patch, api_get_patch:  # type: ignore[attr-defined]
            # TODO why the context is needed if we already have a class-level patch?
            self.harness.begin_with_initial_hooks()

    def test_num_peers(self):
        self.assertEqual(0, len(self.harness.charm.peer_relation.units))

    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def test_pebble_layer_added(self, *unused):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():  # type: ignore[attr-defined]
            self.harness.container_pebble_ready(self.container_name)
        plan = self.harness.get_container_pebble_plan(self.container_name)

        # Check we've got the plan as expected
        self.assertIsNotNone(plan.services)
        self.assertIsNotNone(service := plan.services.get(self.harness.charm._service_name))
        self.assertIsNotNone(command := service.command)

        # Check command is as expected
        self.assertEqual(plan.services, self.harness.charm._alertmanager_layer().services)

        # Check command contains key arguments
        self.assertIn("--config.file", command)
        self.assertIn("--storage.path", command)
        self.assertIn("--web.listen-address", command)
        self.assertIn("--cluster.listen-address", command)

        # Check the service was started
        service = self.harness.model.unit.get_container("alertmanager").get_service("alertmanager")
        self.assertTrue(service.is_running())

    def test_relation_data_provides_public_address(self):
        rel = self.harness.charm.framework.model.get_relation("alerting", self.relation_id)
        expected_address = "1.1.1.1:{}".format(self.harness.charm.alertmanager_provider.api_port)
        self.assertEqual({"public_address": expected_address}, rel.data[self.harness.charm.unit])

    def test_dummy_receiver_used_when_no_config_provided(self):
        self.assertIn("webhook_configs", self.push_pull_mock.pull(self.harness.charm._config_path))
        self.assertIn(
            "http://127.0.0.1:5001/", self.push_pull_mock.pull(self.harness.charm._config_path)
        )

    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def test_topology_added_if_user_provided_config_without_group_by(self, *unused):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():  # type: ignore[attr-defined]
            self.harness.container_pebble_ready(self.container_name)

            new_config = yaml.dump({"not a real config": "but good enough for testing"})
            self.harness.update_config({"config_file": new_config})
            updated_config = yaml.safe_load(
                self.push_pull_mock.pull(self.harness.charm._config_path)
            )

            self.assertEqual(updated_config["not a real config"], "but good enough for testing")
            self.assertListEqual(
                sorted(updated_config["route"]["group_by"]),
                sorted(["juju_model", "juju_application", "juju_model_uuid"]),
            )

    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def test_topology_added_if_user_provided_config_with_group_by(self, *unused):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():  # type: ignore[attr-defined]
            self.harness.container_pebble_ready(self.container_name)

            new_config = yaml.dump({"route": {"group_by": ["alertname", "juju_model"]}})
            self.harness.update_config({"config_file": new_config})
            updated_config = yaml.safe_load(
                self.push_pull_mock.pull(self.harness.charm._config_path)
            )

            self.assertListEqual(
                sorted(updated_config["route"]["group_by"]),
                sorted(["alertname", "juju_model", "juju_application", "juju_model_uuid"]),
            )

    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def test_charm_blocks_if_user_provided_config_with_templates(self, *unused):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():  # type: ignore[attr-defined]
            self.harness.container_pebble_ready(self.container_name)

            new_config = yaml.dump({"templates": ["/what/ever/*.tmpl"]})
            self.harness.update_config({"config_file": new_config})
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

            new_config = yaml.dump({})
            self.harness.update_config({"config_file": new_config})
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)


@patch_network_get(private_address="1.1.1.1")
@patch.object(Alertmanager, "reload", tautology)
class TestWithoutInitialHooks(unittest.TestCase):
    container_name: str = "alertmanager"

    @patch.object(AlertmanagerCharm, "_patch_k8s_service", lambda *a, **kw: None)
    @patch("ops.testing._TestingPebbleClient.push")
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        self.push_pull_mock = PushPullMock()
        self.push_pull_mock.push(AlertmanagerCharm._config_path, alertmanager_default_config)

        self.relation_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        self.harness.set_leader(True)

        network_get_patch = patch_network_get(private_address="1.1.1.1")
        api_get_patch = patch("charm.Alertmanager._get", lambda *a, **kw: None)

        with network_get_patch, api_get_patch:  # type: ignore[attr-defined]
            self.harness.begin()
            self.harness.add_relation("replicas", "alertmanager")

    @patch("ops.testing._TestingPebbleClient.get_system_info")
    def test_unit_status_around_pebble_ready(self, *unused):
        # before pebble_ready, status should be "maintenance"
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.MaintenanceStatus)

        # after pebble_ready, status should be "active"
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():  # type: ignore[attr-defined]
            self.harness.container_pebble_ready(self.container_name)
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.ActiveStatus)

        self.assertEqual(self.harness.model.unit.name, "alertmanager-k8s/0")

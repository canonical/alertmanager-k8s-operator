#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops
import yaml
from helpers import tautology
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import Alertmanager, AlertmanagerCharm

ops.testing.SIMULATE_CAN_CONNECT = True


class TestWithInitialHooks(unittest.TestCase):
    container_name: str = "alertmanager"

    @patch.object(Alertmanager, "reload", tautology)
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        self.relation_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        self.harness.set_leader(True)

        self.harness.begin_with_initial_hooks()

    def test_num_peers(self):
        self.assertEqual(0, len(self.harness.charm.peer_relation.units))  # type: ignore

    def test_pebble_layer_added(self, *unused):
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
        # to suppress mypy error: Item "None" of "Optional[Any]" has no attribute "get_relation"
        model = self.harness.charm.framework.model
        assert model is not None

        rel = model.get_relation("alerting", self.relation_id)
        expected_address = "fqdn:{}".format(self.harness.charm.alertmanager_provider.api_port)
        self.assertEqual({"public_address": expected_address}, rel.data[self.harness.charm.unit])

    def test_topology_added_if_user_provided_config_without_group_by(self, *unused):
        self.harness.container_pebble_ready(self.container_name)

        new_config = yaml.dump({"not a real config": "but good enough for testing"})
        self.harness.update_config({"config_file": new_config})
        updated_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._config_path)
        )

        self.assertEqual(updated_config["not a real config"], "but good enough for testing")
        self.assertListEqual(
            sorted(updated_config["route"]["group_by"]),
            sorted(["juju_model", "juju_application", "juju_model_uuid"]),
        )

    def test_topology_added_if_user_provided_config_with_group_by(self, *unused):
        self.harness.container_pebble_ready(self.container_name)

        new_config = yaml.dump({"route": {"group_by": ["alertname", "juju_model"]}})
        self.harness.update_config({"config_file": new_config})
        updated_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._config_path)
        )

        self.assertListEqual(
            sorted(updated_config["route"]["group_by"]),
            sorted(["alertname", "juju_model", "juju_application", "juju_model_uuid"]),
        )

    def test_charm_blocks_if_user_provided_config_with_templates(self, *unused):
        self.harness.container_pebble_ready(self.container_name)

        new_config = yaml.dump({"templates": ["/what/ever/*.tmpl"]})
        self.harness.update_config({"config_file": new_config})
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        new_config = yaml.dump({})
        self.harness.update_config({"config_file": new_config})
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    def test_templates_section_added_if_user_provided_templates(self, *unused):
        self.harness.container_pebble_ready(self.container_name)

        templates = '{{ define "some.tmpl.variable" }}whatever it is{{ end}}'
        self.harness.update_config({"templates_file": templates})
        updated_templates = self.harness.charm.container.pull(self.harness.charm._templates_path)
        self.assertEqual(templates, updated_templates.read())

        updated_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._config_path)
        )
        self.assertEqual(updated_config["templates"], [f"{self.harness.charm._templates_path}"])


class TestWithoutInitialHooks(unittest.TestCase):
    container_name: str = "alertmanager"

    @patch.object(Alertmanager, "reload", tautology)
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        self.relation_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        self.harness.set_leader(True)

        self.harness.begin()
        self.harness.add_relation("replicas", "alertmanager")

    def test_unit_status_around_pebble_ready(self, *unused):
        # before pebble_ready, status should be "maintenance"
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.MaintenanceStatus)

        # after pebble_ready, status should be "active"
        self.harness.container_pebble_ready(self.container_name)
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.ActiveStatus)

        self.assertEqual(self.harness.model.unit.name, "alertmanager-k8s/0")

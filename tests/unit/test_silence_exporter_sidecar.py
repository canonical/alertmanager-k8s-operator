#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests for the silence-exporter sidecar wiring in the charm."""

import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from helpers import k8s_resource_multipatch
from ops.testing import Harness

from alertmanager import WorkloadManager
from charm import AlertmanagerCharm

RULES_DIR = Path(__file__).parent.parent.parent / "src" / "prometheus_alert_rules"


class TestSilenceExporterSidecar(unittest.TestCase):
    container_name = "silence-exporter"

    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
    @k8s_resource_multipatch
    @patch.object(WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0"))
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.add_relation("replicas", "am")
        self.harness.begin_with_initial_hooks()

    def test_exporter_port_is_opened(self):
        opened = {p.port for p in self.harness.charm.unit.opened_ports()}
        self.assertIn(self.harness.charm._ports.exporter, opened)

    def test_sidecar_layer_and_script_pushed(self):
        self.harness.set_can_connect(self.container_name, True)
        self.harness.container_pebble_ready(self.container_name)

        container = self.harness.model.unit.get_container(self.container_name)

        # The exporter script is pushed into the container.
        pushed = container.pull(self.harness.charm._exporter_script_path).read()
        expected = (
            Path(__file__).parent.parent.parent / "src" / "silence_exporter.py"
        ).read_text()
        self.assertEqual(pushed, expected)

        # The Pebble service is defined and runs the exporter.
        service = container.get_plan().services[self.harness.charm._exporter_service_name]
        self.assertEqual(service.command, "python3 /exporter.py")
        self.assertEqual(service.startup, "enabled")
        env = service.environment
        self.assertEqual(env["EXPORTER_PORT"], "9095")
        self.assertIn("AM_URL", env)
        # No TLS configured -> no CA path in the env.
        self.assertNotIn("AM_CA_PATH", env)


class TestSilenceExpiringSoonRule(unittest.TestCase):
    def test_rule_file_is_valid_yaml(self):
        rule_path = RULES_DIR / "silence_expiring_soon.rule"
        self.assertTrue(rule_path.exists())
        parsed = yaml.safe_load(rule_path.read_text())
        self.assertIn("groups", parsed)
        group = parsed["groups"][0]
        self.assertEqual(group["name"], "SilenceExpiringSoon")
        self.assertEqual(group["rules"][0]["alert"], "SilenceExpiringSoon")


if __name__ == "__main__":
    unittest.main()

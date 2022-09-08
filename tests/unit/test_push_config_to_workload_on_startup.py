#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import patch

import hypothesis.strategies as st
import ops
import validators
import yaml
from helpers import FakeProcessVersionCheck, k8s_resource_multipatch, tautology
from hypothesis import given
from ops.model import ActiveStatus, BlockedStatus, Container
from ops.testing import Harness

from charm import Alertmanager, AlertmanagerCharm

logger = logging.getLogger(__name__)
ops.testing.SIMULATE_CAN_CONNECT = True
CONTAINER_NAME = "alertmanager"


class TestPushConfigToWorkloadOnStartup(unittest.TestCase):
    """Feature: Push config to workload on startup.

    Background: Charm starts up with initial hooks.
    """

    @patch.object(Alertmanager, "reload", tautology)
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", ""))
    @patch("charm.KubernetesServicePatch", lambda *a, **kw: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self, *_):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        # self.harness.charm.app.name does not exist before .begin()
        # https://github.com/canonical/operator/issues/675
        self.app_name = "alertmanager-k8s"
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready(CONTAINER_NAME)

    @given(st.booleans())
    def test_single_unit_cluster(self, is_leader):
        """Scenario: Current unit is the only unit present."""
        # WHEN only one unit is
        self.assertEqual(self.harness.model.app.planned_units(), 1)
        self.harness.set_leader(is_leader)

        # THEN amtool config is rendered
        amtool_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._amtool_config_path)
        )
        self.assertTrue(validators.url(amtool_config["alertmanager.url"]))

        # AND alertmanager config is rendered
        am_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._config_path)
        )
        self.assertGreaterEqual(am_config.keys(), {"global", "route", "receivers"})

        # AND path to config file is part of pebble layer command
        command = (
            self.harness.get_container_pebble_plan(self.harness.charm._container_name)
            .services[self.harness.charm._service_name]
            .command
        )
        self.assertIn(f"--config.file={self.harness.charm._config_path}", command)

        # AND peer clusters cli arg is not present in pebble layer command
        self.assertNotIn("--cluster.peer=", command)

    @k8s_resource_multipatch
    def test_multi_unit_cluster(self, *_):
        """Scenario: Current unit is a part of a multi-unit cluster."""
        self.harness.set_leader(False)

        # WHEN multiple units are present
        num_units = 3
        for i in range(1, num_units):
            self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
            self.harness.update_relation_data(
                self.peer_rel_id,
                f"{self.app_name}/{i}",
                {"private_address": f"http://fqdn-{i}"},
            )

        self.assertEqual(self.harness.model.app.planned_units(), num_units)

        # THEN peer clusters cli arg is present in pebble layer command
        command = (
            self.harness.get_container_pebble_plan(self.harness.charm._container_name)
            .services[self.harness.charm._service_name]
            .command
        )
        self.assertIn("--cluster.peer=", command)

    def test_charm_blocks_on_connection_error(self):
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)
        self.harness.set_can_connect(CONTAINER_NAME, False)
        self.harness.update_config({"templates_file": "doesn't matter"})
        self.assertNotIsInstance(self.harness.charm.unit.status, ActiveStatus)


class TestInvalidConfig(unittest.TestCase):
    """Feature: Charm must block when invalid config is provided.

    Background: alertmanager exits when config is invalid, so this must be guarded against,
    otherwise pebble will keep trying to restart it, resulting in an idle crash-loop.
    """

    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

    @patch.object(Alertmanager, "reload", tautology)
    @patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("", "some error"))
    @patch("charm.KubernetesServicePatch", lambda *a, **kw: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_charm_blocks_on_invalid_config_on_startup(self, *_):
        # GIVEN an invalid config file (mocked above)
        # WHEN the charm starts
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready(CONTAINER_NAME)

        # THEN the charm goes into blocked status
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

    @patch.object(Alertmanager, "reload", tautology)
    @patch("charm.KubernetesServicePatch", lambda *a, **kw: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_charm_blocks_on_invalid_config_changed(self, *_):
        # GIVEN a valid configuration (mocked below)
        with patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("ok", "")):
            # WHEN the charm starts
            self.harness.begin_with_initial_hooks()
            self.harness.container_pebble_ready(CONTAINER_NAME)

            # THEN the charm goes into active status
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        # AND WHEN the config is updated and invalid (mocked below)
        with patch.object(AlertmanagerCharm, "_check_config", lambda *a, **kw: ("", "some error")):
            self.harness.update_config({"config_file": "foo: bar"})

            # THEN the charm goes into blocked status
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

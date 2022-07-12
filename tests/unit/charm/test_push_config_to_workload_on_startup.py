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
from helpers import tautology
from hypothesis import given
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
    @patch("charm.KubernetesServicePatch", lambda *a, **kw: None)
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

    @given(st.booleans(), st.integers(2, 10))
    def test_multi_unit_cluster(self, is_leader, num_units):
        """Scenario: Current unit is a part of a multi-unit cluster."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # WHEN multiple units are present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
                self.harness.update_relation_data(
                    self.peer_rel_id,
                    f"{self.app_name}/{i}",
                    {"private_address": f"http://fqdn-{i}"},
                )

            self.assertEqual(self.harness.model.app.planned_units(), num_units)
            self.harness.set_leader(is_leader)

            # THEN peer clusters cli arg is present in pebble layer command
            command = (
                self.harness.get_container_pebble_plan(self.harness.charm._container_name)
                .services[self.harness.charm._service_name]
                .command
            )
            self.assertIn("--cluster.peer=", command)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

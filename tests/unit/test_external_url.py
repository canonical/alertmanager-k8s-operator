#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import patch
from ops.model import ActiveStatus, BlockedStatus
import ops
import yaml
from helpers import cli_arg, tautology
from ops.testing import Harness

from charm import Alertmanager, AlertmanagerCharm

logger = logging.getLogger(__name__)

ops.testing.SIMULATE_CAN_CONNECT = True
CONTAINER_NAME = "alertmanager"
SERVICE_NAME = AlertmanagerCharm._service_name


class TestExternalUrl(unittest.TestCase):
    @patch.object(Alertmanager, "reload", tautology)
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.harness.set_model_name(self.__class__.__name__)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)

        # Peer relation
        self.app_name = "alertmanager-k8s"
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # Regular relation
        self.rel_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.rel_id, "otherapp/0")

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.fqdn_url = f"http://fqdn:{self.harness.charm.api_port}"

    def get_url_cli_arg(self) -> str:
        plan = self.harness.get_container_pebble_plan(CONTAINER_NAME)
        return cli_arg(plan, "--web.external-url")

    def get_cluster_args(self):
        plan = self.harness.get_container_pebble_plan(CONTAINER_NAME).to_dict()
        args = plan["services"][SERVICE_NAME]["command"].split()
        cluster_args = filter(lambda s: s.startswith("--cluster.peer="), args)
        cluster_args = sorted(map(lambda s: s.split("=")[1], cluster_args))
        return cluster_args

    def is_service_running(self) -> bool:
        # service = plan.services.get(self.harness.charm._service_name)
        service = self.harness.model.unit.get_container(CONTAINER_NAME).get_service(SERVICE_NAME)
        return service.is_running()

    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def test_config_option_overrides_fqdn(self):
        """The config option for external url must override all other external urls."""
        # GIVEN a charm with the fqdn as its external URL
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())

        # WHEN the web_external_url config option is set
        external_url = "http://foo.bar:8080/path/to/alertmanager"
        self.harness.update_config({"web_external_url": external_url})

        # THEN it is used as the cli arg instead of the fqdn
        self.assertEqual(self.get_url_cli_arg(), external_url)
        self.assertTrue(self.is_service_running())

        # WHEN the web_external_url config option is cleared
        self.harness.update_config(unset=["web_external_url"])

        # THEN the cli arg is reverted to the fqdn
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())

    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def test_config_option_overrides_traefik(self):
        """The config option for external url must override all other external urls."""
        # GIVEN a charm with the fqdn as its external URL
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())

        # WHEN a relation with traefik is formed but ingress isn't ready
        rel_id = self.harness.add_relation("ingress", "traefik-app")
        self.harness.add_relation_unit(rel_id, "traefik-app/0")

        # THEN there is no change to the cli arg
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())

        # WHEN ingress becomes available
        external_url_ingress = "http://foo.bar.ingress:80/path/to/mdl-alertmanager-k8s"
        app_data = {"ingress": yaml.safe_dump({"url": external_url_ingress})}
        self.harness.update_relation_data(rel_id, "traefik-app", app_data)

        # THEN the external url from the ingress relation overrides the fqdn
        self.assertEqual(self.get_url_cli_arg(), external_url_ingress)
        self.assertTrue(self.is_service_running())

        # WHEN the web_external_url config option is set
        external_url_config = "http://foo.bar.config:8080/path/to/alertmanager"
        self.harness.update_config({"web_external_url": external_url_config})

        # THEN it is used as the cli arg instead of the ingress
        self.assertEqual(self.get_url_cli_arg(), external_url_config)
        self.assertTrue(self.is_service_running())

        # AND WHEN the web_external_url config option is cleared
        self.harness.update_config(unset=["web_external_url"])

        # THEN the cli arg is reverted to the ingress
        self.assertEqual(self.get_url_cli_arg(), external_url_ingress)
        self.assertTrue(self.is_service_running())

    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def test_web_route_prefix(self):
        # GIVEN a charm with an external web route prefix
        external_url = "http://foo.bar:8080/path/to/alertmanager/"

        self.harness.update_config({"web_external_url": external_url})

        self.assertEqual(self.get_url_cli_arg(), external_url)
        self.assertTrue(self.is_service_running())

        # THEN peer relation data is updated with the web route prefix
        peer_data = self.harness.get_relation_data(self.peer_rel_id, self.harness.charm.unit.name)
        self.assertEqual(peer_data, {"private_address": "http://fqdn:9093/path/to/alertmanager/"})

        # AND the "alerting" relation data is updated with the external url's route prefix (path)
        regular_data = self.harness.get_relation_data(self.rel_id, self.harness.charm.unit.name)
        self.assertEqual(
            regular_data,
            {
                "public_address": "foo.bar:8080/path/to/alertmanager/",
            },
        )

        # AND amtool config file is updated with the web route prefix
        am_config = yaml.safe_load(
            self.harness.charm.container.pull(self.harness.charm._amtool_config_path)
        )
        self.assertEqual(
            am_config["alertmanager.url"],
            f"http://localhost:{self.harness.charm._api_port}/path/to/alertmanager/",
        )

    @patch("socket.getfqdn", new=lambda *args: "fqdn-0")
    def test_cluster_addresses(self):
        # GIVEN an alertmanager charm with 3 units in total
        for u in [1, 2]:
            unit_name = self.app_name + f"/{u}"
            self.harness.add_relation_unit(self.peer_rel_id, unit_name)
            self.harness.update_relation_data(
                self.peer_rel_id, unit_name, {"private_address": f"http://fqdn-{u}:9093"}
            )

        # THEN the `--cluster.peer` args are made up of the hostname and HA port
        cluster_args = self.get_cluster_args()
        self.assertEqual(cluster_args, ["fqdn-1:9094", "fqdn-2:9094"])  # cluster is on ha-port

        # WHEN an external url without a path is set
        self.harness.update_config({"web_external_url": "http://foo.bar:8080/"})

        # THEN the `--cluster.peer` args are made up of the hostname and HA port
        cluster_args = self.get_cluster_args()
        self.assertEqual(cluster_args, ["fqdn-1:9094", "fqdn-2:9094"])

        # WHEN an external url with a path is set
        self.harness.update_config(
            {"web_external_url": "http://foo.bar:8080/path/to/alertmanager"}
        )
        for u in [1, 2]:
            unit_name = self.app_name + f"/{u}"
            self.harness.update_relation_data(
                self.peer_rel_id,
                unit_name,
                {"private_address": f"http://fqdn-{u}:9093/path/to/alertmanager"},
            )

        # THEN the `--cluster.peer` args are made up of the hostname, the HA port and the path
        cluster_args = self.get_cluster_args()
        self.assertEqual(
            cluster_args, ["fqdn-1:9094/path/to/alertmanager", "fqdn-2:9094/path/to/alertmanager"]
        )

    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def test_invalid_web_route_prefix(self):
        for invalid_url in ["htp://foo.bar", "foo.bar"]:
            with self.subTest(url=invalid_url):
                # WHEN the external url config option is invalid
                self.harness.update_config({"web_external_url": invalid_url})

                # THEN the unit is blocked
                self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

                # AND the pebble command arg is unchanged
                self.assertEqual(self.get_url_cli_arg(), "http://fqdn:9093")

                # WHEN the invalid option in cleared
                self.harness.update_config(unset=["web_external_url"])

                # THEN the unit is active
                self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

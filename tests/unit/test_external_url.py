#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops
import yaml
from helpers import cli_arg, tautology
from ops.testing import Harness

from charm import Alertmanager, AlertmanagerCharm

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
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.fqdn_url = f"http://fqdn:{self.harness.charm.api_port}"

    def get_url_cli_arg(self) -> str:
        plan = self.harness.get_container_pebble_plan(CONTAINER_NAME)
        return cli_arg(plan, "--web.external-url")

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

        # AND WHEN the web_external_url config option is cleared
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

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import patch

import ops
import yaml
from alertmanager import WorkloadManager
from charm import Alertmanager, AlertmanagerCharm
from helpers import cli_arg, k8s_resource_multipatch, tautology
from ops.testing import Harness

logger = logging.getLogger(__name__)

ops.testing.SIMULATE_CAN_CONNECT = True
CONTAINER_NAME = "alertmanager"
SERVICE_NAME = AlertmanagerCharm._service_name


class TestExternalUrl(unittest.TestCase):
    @patch.object(Alertmanager, "reload", tautology)
    @patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0"))
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
        self.fqdn_url = f"http://fqdn:{self.harness.charm.api_port}"

    def get_url_cli_arg(self) -> str:
        plan = self.harness.get_container_pebble_plan(CONTAINER_NAME)
        return cli_arg(plan, "--web.external-url")

    def get_cluster_args(self):
        plan = self.harness.get_container_pebble_plan(CONTAINER_NAME).to_dict()
        args = plan["services"][SERVICE_NAME]["command"].split()
        cluster_args = filter(lambda s: s.startswith("--cluster.peer="), args)
        cluster_args = sorted((s.split("=")[1] for s in cluster_args))
        return cluster_args

    def is_service_running(self) -> bool:
        # service = plan.services.get(self.harness.charm._service_name)
        service = self.harness.model.unit.get_container(CONTAINER_NAME).get_service(SERVICE_NAME)
        return service.is_running()

    @unittest.skip("https://github.com/canonical/operator/issues/736")
    @patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @k8s_resource_multipatch
    def test_traefik_overrides_fqdn(self):
        """The config option for external url must override all other external urls."""
        # GIVEN a charm with the fqdn as its external URL
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())
        self.assertEqual(self.harness.charm._external_url, self.fqdn_url)

        # WHEN a relation with traefik is formed but ingress isn't ready
        rel_id = self.harness.add_relation("ingress", "traefik-app")
        self.harness.add_relation_unit(rel_id, "traefik-app/0")

        # THEN there is no change to the cli arg
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)
        self.assertTrue(self.is_service_running())
        self.assertEqual(self.harness.charm._external_url, self.fqdn_url)

        # WHEN ingress becomes available
        external_url_ingress = "http://foo.bar.ingress:80/path/to/mdl-alertmanager-k8s"
        app_data = {"ingress": yaml.safe_dump({"url": external_url_ingress})}
        self.harness.update_relation_data(rel_id, "traefik-app", app_data)

        # THEN the external url from the ingress relation overrides the fqdn
        self.assertEqual(self.get_url_cli_arg(), external_url_ingress)
        self.assertTrue(self.is_service_running())

        # NOTE intentionally not emptying out relation data manually
        # FIXME: figure out if we do or do not need to manually empty out relation-data
        #   before relation-broken is emitted.
        #   https://github.com/canonical/operator/issues/888
        app_data = {"ingress": ""}
        self.harness.update_relation_data(rel_id, "traefik-app", app_data)

        # AND WHEN the traefik relation is removed
        self.harness.remove_relation_unit(rel_id, "traefik-app/0")
        self.harness.remove_relation(rel_id)

        # THEN the fqdn is used as external url
        self.assertEqual(self.get_url_cli_arg(), self.fqdn_url)

    @unittest.skip("https://github.com/canonical/operator/issues/736")
    @patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
    @patch("socket.getfqdn", new=lambda *args: "fqdn-0")
    @k8s_resource_multipatch
    def test_cluster_addresses(self, *_):
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

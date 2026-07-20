#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest.mock import PropertyMock, patch

from helpers import k8s_resource_multipatch
from ops.testing import Harness

from alertmanager import WorkloadManager
from charm import AlertmanagerCharm


class TestWithInitialHooks(unittest.TestCase):
    container_name: str = "alertmanager"

    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
    @k8s_resource_multipatch
    @patch.object(WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0"))
    def setUp(self, *unused):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)

        self.harness.set_leader(True)
        self.app_name = "am"
        # Create the peer relation before running harness.begin_with_initial_hooks(), because
        # otherwise it will create it for you and we don't know the rel_id
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        self.harness.begin_with_initial_hooks()

    @patch.object(AlertmanagerCharm, "_internal_url", new_callable=PropertyMock)
    @patch.object(AlertmanagerCharm, "_scheme", new_callable=PropertyMock)
    def test_self_scraping_job_with_no_peers(self, _mock_scheme, _mock_internal_url):
        scheme = "https"
        _mock_scheme.return_value = scheme
        host = "test-internal.url"
        api_netloc = f"{host}:{self.harness.charm._ports.api}"
        exporter_netloc = f"{host}:{self.harness.charm._ports.exporter}"
        _mock_internal_url.return_value = f"{scheme}://{api_netloc}"
        jobs_expected = [
            {
                "metrics_path": "/metrics",
                "scheme": scheme,
                "static_configs": [{"targets": [api_netloc]}],
            },
            {
                "metrics_path": "/metrics",
                "scheme": "http",
                "static_configs": [{"targets": [exporter_netloc]}],
            },
        ]

        jobs = self.harness.charm.self_scraping_job
        self.assertEqual(jobs, jobs_expected)

    @patch.object(WorkloadManager, "check_config")
    @patch.object(AlertmanagerCharm, "_internal_url", new_callable=PropertyMock)
    @patch.object(AlertmanagerCharm, "_scheme", new_callable=PropertyMock)
    def test_self_scraping_job_with_peers(
        self, _mock_scheme, _mock_internal_url, _mock_check_config
    ):
        scheme = "https"
        _mock_scheme.return_value = scheme

        hosts = ["test-internal-0.url", "test-internal-1.url", "test-internal-2.url"]
        api_targets = [f"{host}:{self.harness.charm._ports.api}" for host in hosts]
        exporter_targets = [f"{host}:{self.harness.charm._ports.exporter}" for host in hosts]
        metrics_path = "/metrics"
        _mock_internal_url.return_value = f"{scheme}://{api_targets[0]}"

        jobs_expected = [
            {
                "metrics_path": metrics_path,
                "scheme": scheme,
                "static_configs": [{"targets": api_targets}],
            },
            {
                "metrics_path": metrics_path,
                "scheme": "http",
                "static_configs": [{"targets": exporter_targets}],
            },
        ]

        # Add peers
        for i, host in enumerate(hosts[1:], 1):
            unit_name = f"{self.app_name}/{i}"
            target = f"{host}:{self.harness.charm._ports.api}"
            self.harness.add_relation_unit(self.peer_rel_id, unit_name)
            self.harness.update_relation_data(
                self.peer_rel_id, unit_name, {"private_address": f"{scheme}://{target}"}
            )

        jobs = self.harness.charm.self_scraping_job
        self.assertEqual(jobs_expected, jobs)

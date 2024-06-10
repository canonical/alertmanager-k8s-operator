#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest.mock import patch, PropertyMock

from alertmanager import WorkloadManager
from charm import AlertmanagerCharm
from helpers import k8s_resource_multipatch
from ops.testing import Harness


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

        self.harness.begin_with_initial_hooks()

    @patch.object(AlertmanagerCharm, "_internal_url", new_callable=PropertyMock)
    @patch.object(AlertmanagerCharm, "_scheme", new_callable=PropertyMock)
    def test_self_scraping_job_with_no_peers(self, _mock_scheme, _mock_internal_url):
        scheme = "https"
        _mock_scheme.return_value = scheme
        url_no_scheme = f"test-internal.url:{self.harness.charm._ports.api}"
        _mock_internal_url.return_value = f"{scheme}://{url_no_scheme}"
        jobs_expected = [
            {
                "metrics_path": "/metrics",
                "scheme": scheme,
                "static_configs": [{"targets": [url_no_scheme]}],
            }
        ]

        jobs = self.harness.charm.self_scraping_job
        self.assertEqual(jobs, jobs_expected)
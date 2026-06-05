#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for self-scraping job generation."""

import dataclasses
import json
from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from ops.testing import Context, Relation, State


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
class TestSelfScrapingJobs:
    """Tests for the self_scraping_job property via the self-metrics-endpoint relation."""

    @pytest.fixture
    def initial_state(self, context: Context, fqdn: str) -> State:
        """Set up charm with self-metrics-endpoint relation."""
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = begin_with_initial_hooks_isolated(context, leader=True)

            # Add self-metrics-endpoint relation
            metrics_rel = Relation("self-metrics-endpoint")
            state = add_relation_sequence(context, state, metrics_rel)
            yield state

    def test_self_scraping_job_with_no_peers(self, initial_state: State, fqdn: str):
        """Test self-scraping job generation with no peer units."""
        relation = initial_state.get_relations("self-metrics-endpoint")[0]
        scrape_jobs = json.loads(relation.local_app_data.get("scrape_jobs", "[]"))

        # Should have one job with one target (this unit only)
        assert len(scrape_jobs) == 1
        job = scrape_jobs[0]
        assert job["metrics_path"] == "/metrics"
        assert job["scheme"] == "http"  # No TLS configured
        assert len(job["static_configs"]) == 1
        assert f"{fqdn}:9093" in job["static_configs"][0]["targets"]

    def test_self_scraping_job_with_peers(self, context: Context, initial_state: State, fqdn: str):
        """Test self-scraping job generation with peer units."""
        # Add peer units with their addresses (must include scheme for urlparse)
        peer_rel = initial_state.get_relations("replicas")[0]
        peer_rel_with_units = dataclasses.replace(
            peer_rel,
            peers_data={
                1: {"private_address": "http://am-1.endpoints.cluster.local"},
                2: {"private_address": "http://am-2.endpoints.cluster.local"},
            },
        )
        state = dataclasses.replace(
            initial_state,
            relations=[
                peer_rel_with_units if r.id == peer_rel.id else r for r in initial_state.relations
            ],
        )

        # Run relation_changed to trigger update
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = context.run(context.on.relation_changed(peer_rel_with_units), state)

        relation = state.get_relations("self-metrics-endpoint")[0]
        scrape_jobs = json.loads(relation.local_app_data.get("scrape_jobs", "[]"))

        # Should have one job with all targets (this unit + peers)
        assert len(scrape_jobs) == 1
        job = scrape_jobs[0]
        targets = job["static_configs"][0]["targets"]

        # Verify all units are included as targets
        assert len(targets) == 3
        assert f"{fqdn}:9093" in targets
        assert "am-1.endpoints.cluster.local:9093" in targets
        assert "am-2.endpoints.cluster.local:9093" in targets

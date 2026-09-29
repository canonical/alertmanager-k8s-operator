#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: alertmanager scrapes itself, and every one of its peers, for metrics."""

import dataclasses
from unittest.mock import PropertyMock, patch

import pytest
from ops.testing import Context, State

SCHEME = "https"


@pytest.fixture(autouse=True)
def https_scheme(alertmanager_charm):
    """Serve over HTTPS, so the scheme in the scrape job is distinguishable from the default."""
    with patch.object(alertmanager_charm, "_scheme", new_callable=PropertyMock) as scheme:
        scheme.return_value = SCHEME
        yield


def self_scraping_job(context: Context, state: State):
    with context(context.on.update_status(), state) as mgr:
        return mgr.charm.self_scraping_job


@pytest.mark.parametrize("fqdn", ["test-internal.url"])
def test_scrape_job_targets_only_this_unit_when_it_has_no_peers(
    context: Context, base_state: State, fqdn, port
):
    # GIVEN a single-unit deployment
    # THEN the scrape job targets this unit alone
    assert self_scraping_job(context, base_state) == [
        {
            "metrics_path": "/metrics",
            "scheme": SCHEME,
            "static_configs": [{"targets": [f"{fqdn}:{port}"]}],
        }
    ]


@pytest.mark.parametrize("fqdn", ["test-internal-0.url"])
def test_scrape_job_targets_every_peer(
    context: Context, base_state: State, peer_relation, fqdn, port
):
    # GIVEN a three-unit deployment whose peers have published their addresses
    hostnames = ["test-internal-0.url", "test-internal-1.url", "test-internal-2.url"]
    peers = dataclasses.replace(
        peer_relation,
        peers_data={
            unit: {"private_address": f"{SCHEME}://{hostname}:{port}"}
            for unit, hostname in enumerate(hostnames[1:], 1)
        },
    )
    state = dataclasses.replace(base_state, relations=[peers])

    # THEN the scrape job targets this unit and all of its peers
    assert self_scraping_job(context, state) == [
        {
            "metrics_path": "/metrics",
            "scheme": SCHEME,
            "static_configs": [{"targets": [f"{hostname}:{port}" for hostname in hostnames]}],
        }
    ]

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for generating scrape jobs for the alertmanager charm."""
import json
from unittest.mock import patch

from ops import pebble
import pytest

from scenario import Context, Relation, State, Container, ExecOutput, PeerRelation

from charm import AlertmanagerCharm


@pytest.fixture
def alertmanager_container(tmp_path):
    layer = pebble.Layer(
        {
            "summary": "alertmanager layer",
            "description": "...",
            "services": {
                "alertmanager": {
                    "override": "replace",
                    "summary": "alertmanager",
                    "command": 'alertmanager',
                    "startup": "enabled",
                },
            },
        }
    )

    return Container(
        name="alertmanager",
        can_connect=True,
        layers={"alertmanager": layer},
        service_status={"alertmanager": pebble.ServiceStatus.ACTIVE},
        exec_mock={
            ("update-ca-certificates", "--fresh"): ExecOutput(),
        }
    )


@patch("socket.getfqdn")
@patch.object(AlertmanagerCharm, "_update_ca_certs")
@patch.object(AlertmanagerCharm, "_is_tls_ready", return_value=True)
def test_self_scraping_job_with_no_peers(_mock_is_tls_ready, _mock_update_ca_certs, mock_getfqdn, context, alertmanager_container):
    """TODO"""
    fqdn = "am-0.endpoints.cluster.local"
    mock_getfqdn.return_value = fqdn
    state_in = State(
        leader=True,
        relations=[
            Relation("self-metrics-endpoint")
        ],
        containers=[alertmanager_container]
    )

    jobs_expected = [
        {
            "metrics_path": "/metrics",
            "scheme": "https",
            "static_configs": [{"targets": [fqdn + ":9093"]}],
        }
    ]

    state_out = context.run("config-changed", state_in)
    assert json.loads(state_out.relations[0].local_app_data['scrape_jobs']) == jobs_expected


@patch("socket.getfqdn")
@patch.object(AlertmanagerCharm, "_update_ca_certs")
@patch.object(AlertmanagerCharm, "_is_tls_ready", return_value=True)
def test_self_scraping_job_with_peers(_mock_is_tls_ready, _mock_update_ca_certs, mock_getfqdn, context, alertmanager_container):
    """TODO"""
    scheme = "https"

    targets = [
        f"test-internal-0.url:9093",
        f"test-internal-1.url:9093",
        f"test-internal-2.url:9093",
    ]
    metrics_path = "/metrics"
    mock_getfqdn.return_value = "test-internal-0.url"

    jobs_expected = [
        {
            "metrics_path": metrics_path,
            "scheme": scheme,
            "static_configs": [{"targets": targets}],
        }
    ]

    replica_relations = [PeerRelation("replicas", local_unit_data={"private_address": f"{scheme}://{target}"}) for target in targets[1:]]

    state_in = State(
        leader=True,
        relations=[
            Relation("self-metrics-endpoint"),
            *replica_relations
        ],
        containers=[alertmanager_container]
    )

    state_out = context.run("config-changed", state_in)
    assert json.loads(state_out.relations[0].local_app_data['scrape_jobs']) == jobs_expected

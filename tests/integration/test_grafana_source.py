# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager as a Grafana datasource."""

import logging
from pathlib import Path

import jubilant
import pytest
from helpers import ALERTMANAGER_IMAGE, grafana_datasources
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

AM_APP = "am"
GRAFANA_APP = "grafana"
TRAEFIK_APP = "traefik"


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        num_units=2,
        trust=True,
    )
    juju.deploy("grafana-k8s", GRAFANA_APP, channel="dev/edge", trust=True)
    juju.integrate(f"{GRAFANA_APP}:grafana-source", AM_APP)
    juju.wait(
        lambda s: (
            jubilant.all_active(s, AM_APP, GRAFANA_APP)
            and jubilant.all_agents_idle(s, AM_APP, GRAFANA_APP)
        ),
        timeout=600,
        delay=30,
        successes=3,
    )


@retry(wait=wait_fixed(10), stop=stop_after_attempt(6), reraise=True)
def _get_datasources(juju) -> list:
    sources = grafana_datasources(juju, GRAFANA_APP)
    assert sources, "No datasources available yet"
    return sources


def test_single_datasource(juju):
    sources = _get_datasources(juju)
    assert len(sources) == 1, f"Expected 1 datasource, got {len(sources)}: {sources}"


def test_datasource_url_uses_service_endpoint(juju):
    sources = _get_datasources(juju)
    assert sources[0]["url"].startswith("http://am-endpoints"), (
        f"Expected datasource URL to start with 'http://am-endpoints', got: {sources[0]['url']}"
    )


def test_deploy_traefik_and_integrate(juju):
    juju.deploy("traefik-k8s", TRAEFIK_APP, channel="edge", trust=True)
    juju.integrate(f"{TRAEFIK_APP}:ingress", AM_APP)
    juju.wait(
        lambda s: (
            jubilant.all_active(s, AM_APP, GRAFANA_APP, TRAEFIK_APP)
            and jubilant.all_agents_idle(s, AM_APP, GRAFANA_APP, TRAEFIK_APP)
        ),
        timeout=600,
        delay=30,
        successes=3,
    )


def test_datasource_url_not_pod_endpoint_after_ingress(juju):
    sources = _get_datasources(juju)
    assert len(sources) == 1, f"Expected 1 datasource after traefik, got {len(sources)}: {sources}"
    assert "am-endpoints" not in sources[0]["url"], (
        f"Expected datasource URL to not contain 'am-endpoints', got: {sources[0]['url']}"
    )

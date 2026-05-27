#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the logging (log forwarding) relation."""

import logging
from pathlib import Path

import jubilant
import pytest
import requests
from helpers import ALERTMANAGER_IMAGE, get_unit_address
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

APP_NAME = "alertmanager"
LOKI_APP = "loki"


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        APP_NAME,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    juju.deploy("loki-k8s", LOKI_APP, channel="dev/edge", trust=True)
    juju.wait(
        lambda s: jubilant.all_active(s, APP_NAME, LOKI_APP)
        and jubilant.all_agents_idle(s, APP_NAME, LOKI_APP),
        timeout=600,
        delay=30,
        successes=3,
    )


def test_logging_integration(juju):
    juju.integrate(f"{APP_NAME}:logging", f"{LOKI_APP}:logging")
    juju.wait(
        lambda s: jubilant.all_active(s, APP_NAME, LOKI_APP)
        and jubilant.all_agents_idle(s, APP_NAME, LOKI_APP),
        timeout=300,
        delay=30,
        successes=3,
    )

    @retry(wait=wait_fixed(15), stop=stop_after_attempt(20), reraise=True)
    def _assert_logs():
        loki_address = get_unit_address(juju, LOKI_APP, 0)
        url = f"http://{loki_address}:3100/loki/api/v1/query_range"
        response = requests.get(url, params={"query": f'{{juju_application="{APP_NAME}"}}'})
        response.raise_for_status()
        result = response.json().get("data", {}).get("result", [])
        assert result, f"No log entries found in Loki for {APP_NAME}"

    _assert_logs()

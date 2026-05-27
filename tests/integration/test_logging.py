#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the logging (log forwarding) relation."""

# pyright: reportAttributeAccessIssue = false
# pyright: reportOptionalMemberAccess = false

import asyncio
import logging
from pathlib import Path

import pytest
import requests
import yaml
from helpers import get_unit_address
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_fixed

pytestmark = pytest.mark.usefixtures("setup_env")

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Deploy the alertmanager charm and loki, then integrate via logging."""
    await asyncio.gather(
        ops_test.model.deploy(charm_under_test, APP_NAME, resources=RESOURCES, trust=True),
        ops_test.model.deploy("loki-k8s", "loki", channel="dev/edge", trust=True),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, "loki"], status="active")


@pytest.mark.abort_on_fail
async def test_logging_integration(ops_test: OpsTest):
    """Integrate alertmanager with loki via the logging relation."""
    await ops_test.model.add_relation(f"{APP_NAME}:logging", "loki:logging")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, "loki"], status="active")


@retry(wait=wait_fixed(15), stop=stop_after_attempt(20))
async def test_logs_are_forwarded_to_loki(ops_test: OpsTest):
    """Verify that alertmanager logs are present in Loki."""
    loki_address = await get_unit_address(ops_test, "loki", 0)
    url = f"http://{loki_address}:3100/loki/api/v1/query_range"
    response = requests.get(url, params={"query": f'{{juju_application="{APP_NAME}"}}'})
    response.raise_for_status()

    result = response.json().get("data", {}).get("result", [])
    assert len(result) > 0, f"No log entries found in Loki for {APP_NAME}"

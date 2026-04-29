#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the logging (log forwarding) relation."""

# pyright: reportAttributeAccessIssue = false
# pyright: reportOptionalMemberAccess = false

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Deploy the alertmanager charm and loki, then integrate via logging."""
    await asyncio.gather(
        ops_test.model.deploy(
            charm_under_test, app_name, resources=resources, trust=True
        ),
        ops_test.model.deploy("loki-k8s", "loki", channel="latest/stable", trust=True),
    )
    await ops_test.model.wait_for_idle(
        apps=[app_name, "loki"], status="active", timeout=600
    )


@pytest.mark.abort_on_fail
async def test_logging_integration(ops_test: OpsTest):
    """Integrate alertmanager with loki via the logging relation."""
    await ops_test.model.add_relation(f"{app_name}:logging", "loki:logging")
    await ops_test.model.wait_for_idle(
        apps=[app_name, "loki"], status="active", timeout=300
    )

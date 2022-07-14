#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests alertmanager upgrade with and without relations present.

1. Deploy the charm under test _from charmhub_.
2. Refresh with locally built charm.
3. Add all supported relations.
4. Refresh with locally built charm.
5. Add unit and refresh again (test multi unit upgrade with relations).
"""

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import is_alertmanager_up
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config(
        {"update-status-hook-interval": "60m", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )


@pytest.mark.abort_on_fail
async def test_upgrade_edge_with_local_in_isolation(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test, deploy the charm from charmhub, and upgrade from path."""
    logger.info("deploy charm from charmhub")
    await ops_test.model.deploy("ch:alertmanager-k8s", application_name=app_name, channel="edge")
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    logger.info("upgrade deployed charm with local charm %s", charm_under_test)
    await ops_test.model.applications[app_name].refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_upgrade_local_with_local_with_relations(ops_test: OpsTest, charm_under_test):
    # Deploy related apps
    await asyncio.gather(
        ops_test.model.deploy(
            "ch:prometheus-k8s", application_name="prom", channel="edge", trust=True
        ),
        ops_test.model.deploy("ch:karma-k8s", application_name="karma", channel="edge"),
    )

    # Relate apps
    await asyncio.gather(
        ops_test.model.add_relation(app_name, "prom:alertmanager"),
        ops_test.model.add_relation(app_name, "karma"),
    )

    # Refresh from path
    await ops_test.model.applications[app_name].refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"], status="active", timeout=2500
    )
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_upgrade_with_multiple_units(ops_test: OpsTest, charm_under_test):
    # Add unit
    await ops_test.model.applications[app_name].scale(scale_change=1)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"], status="active", timeout=1000
    )

    # Refresh from path
    await ops_test.model.applications[app_name].refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"], status="active", timeout=2500
    )
    assert await is_alertmanager_up(ops_test, app_name)

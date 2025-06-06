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

import logging
from pathlib import Path

import pytest
import sh
import yaml
from helpers import is_alertmanager_up
from pytest_operator.plugin import OpsTest

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_setup_env(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.set_config(
        {"update-status-hook-interval": "60m", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )


@pytest.mark.abort_on_fail
async def test_upgrade_edge_with_local_in_isolation(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test, deploy the charm from charmhub, and upgrade from path."""
    logger.info("deploy charm from charmhub")
    assert ops_test.model
    sh.juju.deploy(app_name, model=ops_test.model.name, channel="2/edge", trust=True)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    logger.info("upgrade deployed charm with local charm %s", charm_under_test)
    application = ops_test.model.applications[app_name]
    assert application
    sh.juju.refresh(app_name, model=ops_test.model.name, path=charm_under_test)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, raise_on_error=False
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=30)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_upgrade_local_with_local_with_relations(ops_test: OpsTest, charm_under_test):
    # Deploy related apps
    assert ops_test.model
    sh.juju.deploy(
        "prometheus-k8s", "prom", model=ops_test.model.name, channel="2/edge", trust=True
    )
    sh.juju.deploy("karma-k8s", "karma", model=ops_test.model.name, channel="2/edge", trust=True)

    # Relate apps
    sh.juju.relate(app_name, "prom:alertmanager", model=ops_test.model.name)
    sh.juju.relate(app_name, "karma", model=ops_test.model.name)

    # Refresh from path
    application = ops_test.model.applications[app_name]
    assert application
    sh.juju.refresh(app_name, model=ops_test.model.name, path=charm_under_test)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"],
        status="active",
        timeout=2500,
        raise_on_error=False,
    )
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_upgrade_with_multiple_units(ops_test: OpsTest, charm_under_test):
    assert ops_test.model
    # Add unit
    application = ops_test.model.applications[app_name]
    assert application
    await application.scale(scale_change=1)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"], status="active", timeout=1000
    )

    # Refresh from path
    sh.juju.refresh(app_name, model=ops_test.model.name, path=charm_under_test)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prom", "karma"], status="active", timeout=2500
    )
    assert await is_alertmanager_up(ops_test, app_name)

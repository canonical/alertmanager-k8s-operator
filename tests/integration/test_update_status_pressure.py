#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests common lifecycle behaviors under frequent update-status hook firing.

0. Set update-status frequency to the minimum possible
1. Deploys and relate the charm-under-test
2. Remove related app(s)
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
        {"update-status-hook-interval": "10s", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )


@pytest.mark.abort_on_fail
async def test_deploy_multiple_units(ops_test: OpsTest, charm_under_test):
    """Deploy the charm-under-test."""
    logger.info("build charm from local source folder")

    logger.info("deploy charms")
    await asyncio.gather(
        ops_test.model.deploy(
            charm_under_test, application_name=app_name, resources=resources, num_units=2
        ),
        ops_test.model.deploy("ch:prometheus-k8s", application_name="prom", channel="edge"),
    )

    await asyncio.gather(
        ops_test.model.add_relation(app_name, "prom:alertmanager"),
        ops_test.model.wait_for_idle(status="active", timeout=1000),
    )

    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_remove_related_app(ops_test: OpsTest):
    await ops_test.model.applications["prom"].remove()
    # Block until it is really gone. Added after an itest failed when tried to redeploy:
    # juju.errors.JujuError: ['cannot add application "related-app": application already exists']
    await ops_test.model.block_until(lambda: "prom" not in ops_test.model.applications)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=300)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_wait_through_a_few_update_status_cycles(ops_test: OpsTest):
    await asyncio.sleep(60)  # should be longer than the update-status period

    # "Disable" update-status so the charm gets a chance to become idle for long enough for
    # wait_for_idle to succeed
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=300)

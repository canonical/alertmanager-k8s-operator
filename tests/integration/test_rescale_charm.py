#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests rescaling.

1. Deploys multiple units of the charm under test and waits for them to become active
2. Reset and repeat the above until the leader unit is not the zero unit
3. Scales up the application by a few units and waits for them to become active
4. Scales down the application to below the leader unit, to trigger a leadership change event
"""


import logging
from pathlib import Path

import pytest
import yaml
from helpers import (
    IPAddressWorkaround,
    block_until_leader_elected,
    get_leader_unit_num,
    is_alertmanager_up,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_deploy_multiple_units(ops_test, charm_under_test):
    """Deploy the charm-under-test."""
    logger.info("build charm from local source folder")

    while True:
        logger.info("deploy charm")
        await ops_test.model.deploy(
            charm_under_test, application_name=app_name, resources=resources, num_units=10
        )
        await block_until_leader_elected(ops_test, app_name)

        if await get_leader_unit_num(ops_test, app_name) > 0:
            break

        # we're unlucky: unit/0 is the leader, which means no scale down could trigger a
        # leadership change event - repeat
        logger.info("Elected leader is unit/0 - resetting and repeating")
        await ops_test.model.applications[app_name].remove()
        await ops_test.model.block_until(lambda: len(ops_test.model.applications) == 0)
        await ops_test.model.reset()

    async with IPAddressWorkaround(ops_test):
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_scale_down_to_single_unit_with_leadership_change(ops_test):
    """Scale down below current leader to trigger a leadership change event."""
    await ops_test.model.applications[app_name].scale(scale=1)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=1
    )
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_scale_up_from_single_unit(ops_test):
    """Add a few more units."""
    await ops_test.model.applications[app_name].scale(scale_change=2)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=3
    )
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_scale_down_to_single_unit_without_leadership_change(ops_test):
    """Remove a few units."""
    await ops_test.model.applications[app_name].scale(scale_change=-2)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=1
    )
    assert await is_alertmanager_up(ops_test, app_name)

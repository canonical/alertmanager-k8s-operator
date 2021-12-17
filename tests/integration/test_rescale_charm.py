#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests rescaling.

1. Deploys multiple units of the charm under test and waits for them to become active
2. Reset and repeat the above until the leader unit is not the zero unit
3. Scales up the application by a few units and waits for them to become active
4. Scales down the application to below the leader unit, to trigger a leadership change event
"""


import json
import logging
import urllib.request
from pathlib import Path

import pytest
import yaml
from helpers import (  # type: ignore[attr-defined]
    IPAddressWorkaround,
    block_until_leader_elected,
    get_leader_unit_num,
    get_unit_address,
)

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
# app_name = "am"
app_name = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_deploy_multiple_units(ops_test, charm_under_test):
    """Deploy the charm-under-test."""
    log.info("build charm from local source folder")
    resources = {
        "alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]
    }

    while True:
        log.info("deploy charm")
        await ops_test.model.deploy(
            charm_under_test, application_name=app_name, resources=resources, num_units=10
        )
        await block_until_leader_elected(ops_test, app_name)

        if await get_leader_unit_num(ops_test, app_name) > 0:
            break

        # we're unlucky: unit/0 is the leader, which means no scale down could trigger a
        # leadership change event - repeat
        log.info("Elected leader is unit/0 - resetting and repeating")
        await ops_test.model.applications[app_name].remove()
        await ops_test.model.block_until(lambda: len(ops_test.model.applications) == 0)
        await ops_test.model.reset()

    async with IPAddressWorkaround(ops_test):
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_scale_down_to_single_unit_with_leadership_change(ops_test):
    """Scale down below current leader to trigger a leadership change event."""
    await ops_test.model.applications[app_name].scale(scale=1)

    # block_until is needed because of https://github.com/juju/python-libjuju/issues/608
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) == 1)

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_scale_up_from_single_unit(ops_test):
    """Add a few more units."""
    await ops_test.model.applications[app_name].scale(scale_change=2)

    # block_until is needed because of https://github.com/juju/python-libjuju/issues/608
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) == 3)

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_scale_down_to_single_unit_without_leadership_change(ops_test):
    """Remove a few units."""
    await ops_test.model.applications[app_name].scale(scale_change=-2)

    # block_until is needed because of https://github.com/juju/python-libjuju/issues/608
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) == 1)

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_alertmanager_is_up(ops_test):
    address = await get_unit_address(ops_test, app_name, 0)
    url = f"http://{address}:9093"
    log.info("am public address: %s", url)

    response = urllib.request.urlopen(f"{url}/api/v2/status", data=None, timeout=2.0)
    assert response.code == 200
    assert "versionInfo" in json.loads(response.read())

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import asyncio
import json
import logging
import urllib.request
from typing import Dict

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def get_unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Get private address of a unit."""
    status = await ops_test.model.get_status()  # noqa: F821
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


def interleave(l1: list, l2: list) -> list:
    """Interleave two lists.

    >>> interleave([1,2,3], ['a', 'b', 'c'])
    [1, 'a', 2, 'b', 3, 'c']

    Reference: https://stackoverflow.com/a/11125298/3516684
    """
    return [x for t in zip(l1, l2) for x in t]


async def cli_upgrade_from_path_and_wait(
    ops_test: OpsTest,
    path: str,
    alias: str,
    resources: Dict[str, str] = None,
    wait_for_status: str = None,
):
    if resources is None:
        resources = {}

    resource_pairs = [f"{k}={v}" for k, v in resources.items()]
    resource_arg_prefixes = ["--resource"] * len(resource_pairs)
    resource_args = interleave(resource_arg_prefixes, resource_pairs)

    cmd = [
        "juju",
        "refresh",
        "--path",
        path,
        alias,
        *resource_args,
    ]

    retcode, stdout, stderr = await ops_test.run(*cmd)
    assert retcode == 0, f"Upgrade failed: {(stderr or stdout).strip()}"
    logger.info(stdout)
    await ops_test.model.wait_for_idle(apps=[alias], status=wait_for_status, timeout=120)


async def get_leader_unit_num(ops_test: OpsTest, app_name: str):
    units = ops_test.model.applications[app_name].units
    is_leader = [await units[i].is_leader_from_status() for i in range(len(units))]
    logger.info("Leaders: %s", is_leader)
    return is_leader.index(True)


async def is_leader_elected(ops_test: OpsTest, app_name: str):
    units = ops_test.model.applications[app_name].units
    return any([await units[i].is_leader_from_status() for i in range(len(units))])


async def block_until_leader_elected(ops_test: OpsTest, app_name: str):
    # await ops_test.model.block_until(is_leader_elected)
    # block_until does not take async (yet?) https://github.com/juju/python-libjuju/issues/609
    while not await is_leader_elected(ops_test, app_name):
        await asyncio.sleep(5)


async def is_alertmanage_unit_up(ops_test: OpsTest, app_name: str, unit_num: int):
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = f"http://{address}:9093"
    logger.info("am public address: %s", url)

    response = urllib.request.urlopen(f"{url}/api/v2/status", data=None, timeout=2.0)
    return response.code == 200 and "versionInfo" in json.loads(response.read())


async def is_alertmanager_up(ops_test: OpsTest, app_name: str):
    return all(
        [
            await is_alertmanage_unit_up(ops_test, app_name, unit_num)
            for unit_num in range(len(ops_test.model.applications[app_name].units))
        ]
    )

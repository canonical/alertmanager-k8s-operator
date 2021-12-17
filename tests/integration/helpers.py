# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import logging
from typing import Dict

from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


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

    retcode, stdout, stderr = await ops_test._run(*cmd)
    assert retcode == 0, f"Upgrade failed: {(stderr or stdout).strip()}"
    log.info(stdout)
    await ops_test.model.wait_for_idle(apps=[alias], status=wait_for_status, timeout=120)

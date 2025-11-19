# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import asyncio
import grp
import json
import logging
import urllib.request
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from juju.unit import Unit
from pytest_operator.plugin import OpsTest
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


async def get_unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Get private address of a unit."""
    assert ops_test.model
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
    resources: Optional[Dict[str, str]] = None,
    wait_for_status: Optional[str] = None,
):
    assert ops_test.model
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
    assert ops_test.model
    application = ops_test.model.applications[app_name]
    assert application
    units = application.units
    is_leader = [await units[i].is_leader_from_status() for i in range(len(units))]
    logger.info("Leaders: %s", is_leader)
    return is_leader.index(True)


async def is_leader_elected(ops_test: OpsTest, app_name: str):
    assert ops_test.model
    application = ops_test.model.applications[app_name]
    assert application
    units = application.units
    return any([await units[i].is_leader_from_status() for i in range(len(units))])


async def block_until_leader_elected(ops_test: OpsTest, app_name: str):
    # await ops_test.model.block_until(is_leader_elected)
    # block_until does not take async (yet?) https://github.com/juju/python-libjuju/issues/609
    while not await is_leader_elected(ops_test, app_name):
        await asyncio.sleep(5)


def uk8s_group() -> str:
    try:
        # Classically confined microk8s
        uk8s_group = grp.getgrnam("microk8s").gr_name
    except KeyError:
        # Strictly confined microk8s
        uk8s_group = "snap_microk8s"
    return uk8s_group


async def is_alertmanage_unit_up(ops_test: OpsTest, app_name: str, unit_num: int):
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = f"http://{address}:9093"
    logger.info("am public address: %s", url)

    response = urllib.request.urlopen(f"{url}/api/v2/status", data=None, timeout=2.0)
    return response.code == 200 and "versionInfo" in json.loads(response.read())


async def is_alertmanager_up(ops_test: OpsTest, app_name: str):
    assert ops_test.model
    application = ops_test.model.applications[app_name]
    assert application
    return all(
        [
            await is_alertmanage_unit_up(ops_test, app_name, unit_num)
            for unit_num in range(len(application.units))
        ]
    )


async def get_alertmanager_config_from_file(
    ops_test: OpsTest, app_name: str, container_name: str, config_file_path: str
) -> Tuple[Optional[int], str, str]:
    rc, stdout, stderr = await ops_test.juju(
        "ssh", "--container", f"{container_name}", f"{app_name}/0", "cat", f"{config_file_path}"
    )
    return rc, stdout, stderr


async def deploy_literal_bundle(ops_test: OpsTest, bundle: str):
    run_args = [
        "juju",
        "deploy",
        "--trust",
        "-m",
        ops_test.model_name,
        str(ops_test.render_bundle(bundle)),
    ]

    retcode, stdout, stderr = await ops_test.run(*run_args)
    assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"
    logger.info(stdout)


async def curl(ops_test: OpsTest, *, cert_dir: str, cert_path: str, ip_addr: str, mock_url: str):
    p = urlparse(mock_url)

    # Tell curl to resolve the mock url as traefik's IP (to avoid using a custom DNS
    # server). This is needed because the certificate issued by the CA would have that same
    # hostname as the subject, and for TLS to succeed, the target url's hostname must match
    # the one in the certificate.
    cmd = [
        "curl",
        "-s",
        "--fail-with-body",
        "--resolve",
        f"{p.hostname}:{p.port or 443}:{ip_addr}",
        "--capath",
        str(cert_dir),
        "--cacert",
        str(cert_path),
        mock_url,
    ]
    logger.info("cURL command: '%s'", " ".join(cmd))
    rc, stdout, stderr = await ops_test.run(*cmd)
    logger.info("%s: %s", mock_url, (rc, stdout, stderr))
    assert rc == 0, (
        f"curl exited with rc={rc} for {mock_url}; "
        "non-zero return code means curl encountered a >= 400 HTTP code"
    )
    return stdout

async def grafana_password(ops_test: OpsTest, app_name: str) -> str:
    """Get the admin password. Memoize it to reduce turnaround time.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application

    Returns:
        admin password as a string
    """
    leader: Optional[Unit] = None
    for unit in ops_test.model.applications[app_name].units:  # type: ignore
        is_leader = await unit.is_leader_from_status()
        if is_leader:
            leader = unit
            break

    assert leader
    action = await leader.run_action("get-admin-password")
    action = await action.wait()
    return action.results["admin-password"]

async def grafana_datasources(ops_test: OpsTest, app_name: str) -> "list[dict]":
    """Get the number of datasources configured in Grafana.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
    Returns:
        number of datasources as an integer
    """
    address = await get_unit_address(ops_test, app_name, 0)
    url = f"http://{address}:3000/api/datasources"

    admin_password = await grafana_password(ops_test, app_name)
    response = requests.get(
        url,
        auth=HTTPBasicAuth("admin", admin_password),
    )
    response.raise_for_status()
    datasources = response.json()
    return datasources

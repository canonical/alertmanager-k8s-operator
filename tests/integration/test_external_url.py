#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path

import pytest
import yaml
from helpers import get_unit_address, is_alertmanager_up
from pytest_operator.plugin import OpsTest

from alertmanager_client import Alertmanager

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}
deploy_timeout = 600
config_timeout = 300


@pytest.mark.abort_on_fail
async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config(
        {"update-status-hook-interval": "60m", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    # deploy charm from local source folder
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name=app_name)
    await ops_test.model.wait_for_idle(status="active", timeout=deploy_timeout)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_workload_is_reachable_without_external_url(ops_test: OpsTest):
    # Workload must be reachable from the host via the unit's IP.
    client = Alertmanager(await get_unit_address(ops_test, app_name, 0))
    assert "uptime" in client.status()

    # Workload must be reachable from the charm container via cluster dns.
    rc, stdout, stderr = await ops_test.juju(
        "exec", f"--unit={app_name}/0", "--", "sh", "-c", r"curl $(hostname -f):9093/api/v2/status"
    )
    assert "uptime" in json.loads(stdout)

    # Workload must be reachable from the workload container via "amtool"
    rc, stdout, stderr = await ops_test.juju(
        "ssh", "--container", "alertmanager", f"{app_name}/0", "amtool", "config", "show"
    )
    assert "global" in yaml.safe_load(stdout)  # global is a mandatory section in the config file


@pytest.mark.abort_on_fail
async def test_units_can_communicate_to_form_a_cluster(ops_test: OpsTest):
    await ops_test.model.applications[app_name].scale(scale=3)
    await ops_test.model.wait_for_idle(
        status="active", timeout=deploy_timeout, wait_for_exact_units=3
    )
    client = Alertmanager(await get_unit_address(ops_test, app_name, 0))
    assert len(client.status()["cluster"]["peers"]) == 3


@pytest.mark.abort_on_fail
async def test_workload_is_locally_reachable_with_external_url_with_path(ops_test: OpsTest):
    web_route_prefix = "custom/path/to/alertmanager"
    await ops_test.model.applications[app_name].set_config(
        {"web_external_url": f"http://does.not.matter/{web_route_prefix}"}
    )

    await ops_test.model.wait_for_idle(status="active", timeout=config_timeout)

    # Workload must be reachable from the host via the unit's IP.
    address = await get_unit_address(ops_test, app_name, 0)
    client = Alertmanager(address, web_route_prefix=web_route_prefix)
    assert "uptime" in client.status()

    # Workload must be reachable from the charm container via cluster dns.
    rc, stdout, stderr = await ops_test.juju(
        "exec",
        f"--unit={app_name}/0",
        "--",
        "sh",
        "-c",
        r"curl $(hostname -f):9093/{}/api/v2/status".format(web_route_prefix),
    )
    assert "uptime" in json.loads(stdout)

    # Workload must be reachable from the workload container via "amtool"
    rc, stdout, stderr = await ops_test.juju(
        "ssh", "--container", "alertmanager", f"{app_name}/0", "amtool", "config", "show"
    )
    assert "global" in yaml.safe_load(stdout)

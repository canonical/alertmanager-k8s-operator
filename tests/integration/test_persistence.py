#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from helpers import get_unit_address, is_alertmanager_up, uk8s_group
from pytest_operator.plugin import OpsTest

from src.alertmanager_client import Alertmanager

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_silences_persist_across_upgrades(ops_test: OpsTest, charm_under_test, httpserver):
    assert ops_test.model
    # deploy alertmanager charm from charmhub
    logger.info("deploy charm from charmhub")
    await ops_test.model.deploy(
        "ch:alertmanager-k8s", application_name=app_name, channel="edge", trust=True
    )
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, raise_on_error=False
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=30)

    # set a silencer for an alert and check it is set
    unit_address = await get_unit_address(ops_test, app_name, 0)
    alertmanager = Alertmanager(f"http://{unit_address}:9093")

    silence_start = datetime.now(timezone.utc)
    silence_end = silence_start + timedelta(minutes=30)
    matchers = [
        {
            "name": "alertname",
            "value": "fake-alert",
            "isRegex": False,
        }
    ]
    alertmanager.set_silences(matchers, silence_start, silence_end)
    silences_before = alertmanager.get_silences()
    assert len(silences_before)

    # Use kubectl to send a SIGTERM signal to Alertmanager so that data is flushed to disk.
    # This step should not be necessary once the bug in the following issue ticket is fixed
    # https://github.com/canonical/pebble/issues/122
    # FIXME: remove the following kubectl commands once the above bug is fixed
    pod_name = f"{app_name}-0"
    container_name = "alertmanager"
    sg_cmd = [
        "sg",
        uk8s_group(),
        "-c",
    ]
    kubectl_cmd = [
        "microk8s.kubectl",
        "-n",
        ops_test.model_name,
        "exec",
        pod_name,
        "-c",
        container_name,
        "--",
    ]
    # find pid of alertmanager
    pid_cmd = ["pidof", "alertmanager"]
    cmd = sg_cmd + [" ".join(kubectl_cmd + pid_cmd)]
    retcode, alertmanager_pid, stderr = await ops_test.run(*cmd)
    assert retcode == 0, f"kubectl failed: {(stderr or alertmanager_pid).strip()}"
    # use pid of alertmanager to send it a SIGTERM signal using kubectl
    term_cmd = ["kill", "-s", "TERM", alertmanager_pid]
    cmd = sg_cmd + [" ".join(kubectl_cmd + term_cmd)]
    logger.debug("Sending SIGTERM to Alertmanager")
    retcode, stdout, stderr = await ops_test.run(*cmd)
    assert retcode == 0, f"kubectl failed: {(stderr or stdout).strip()}"
    logger.debug(stdout)
    application = ops_test.model.applications[app_name]
    assert application
    await ops_test.model.block_until(lambda: len(application[app_name].units) > 0)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)

    # upgrade alertmanger using charm built locally
    logger.info("upgrade deployed charm with local charm %s", charm_under_test)
    await application.refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, raise_on_error=False
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=30)
    assert await is_alertmanager_up(ops_test, app_name)

    # check silencer is still set
    unit_address = await get_unit_address(ops_test, app_name, 0)
    alertmanager = Alertmanager(f"http://{unit_address}:9093")
    silences_after = alertmanager.get_silences()
    assert len(silences_after)

    assert silences_before == silences_after

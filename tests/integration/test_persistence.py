#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from datetime import datetime, timedelta, timezone
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


@pytest.mark.abort_on_fail
async def test_silences_persist_across_upgrades(ops_test: OpsTest, charm_under_test, httpserver):
    # deploy alertmanager charm from charmhub
    logger.info("deploy charm from charmhub")
    await ops_test.model.deploy("ch:alertmanager-k8s", application_name=app_name, channel="edge")
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    # set a silencer for an alert and check it is set
    alertmanager = Alertmanager(address=await get_unit_address(ops_test, app_name, 0))

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

    # upgrade alertmanger using charm built locally
    logger.info("upgrade deployed charm with local charm %s", charm_under_test)
    await ops_test.model.applications[app_name].refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)

    # check silencer is still set
    alertmanager = Alertmanager(address=await get_unit_address(ops_test, app_name, 0))
    silences_after = alertmanager.get_silences()
    assert len(silences_after)

    assert silences_before == silences_after

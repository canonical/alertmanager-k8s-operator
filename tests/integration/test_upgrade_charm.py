#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import urllib.request
from pathlib import Path

import pytest
import yaml
from helpers import (  # type: ignore[attr-defined]
    IPAddressWorkaround,
    cli_upgrade_from_path_and_wait,
    get_unit_address,
)

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
# app_name = "am"
app_name = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    log.info("build charm from local source folder")
    resources = {
        "alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]
    }

    async with IPAddressWorkaround(ops_test):
        log.info("deploy charm from charmhub")
        await ops_test.model.deploy(
            "ch:alertmanager-k8s", application_name=app_name, channel="edge"
        )
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

        log.info("upgrade deployed charm with local charm %s", charm_under_test)
        # await ops_test.model.applications[app_name].refresh(
        #     path=local_charm, resources=resources
        # )

        await cli_upgrade_from_path_and_wait(
            ops_test,
            path=charm_under_test,
            alias=app_name,
            resources=resources,
            wait_for_status="active",
        )


@pytest.mark.abort_on_fail
async def test_alertmanager_is_up(ops_test):
    address = await get_unit_address(ops_test, app_name, 0)
    url = f"http://{address}:9093"
    log.info("am public address: %s", url)

    response = urllib.request.urlopen(f"{url}/api/v2/status", data=None, timeout=2.0)
    assert response.code == 200
    assert "versionInfo" in json.loads(response.read())

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import urllib.request
from pathlib import Path

import pytest
import yaml
from helpers import IPAddressWorkaround, get_unit_address  # type: ignore[attr-defined]

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # deploy charm from local source folder
    resources = {
        "alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]
    }
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name="am")

    async with IPAddressWorkaround(ops_test):
        await ops_test.model.wait_for_idle(apps=["am"], status="active", timeout=1000)

    assert ops_test.model.applications["am"].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_alertmanager_is_up(ops_test):
    address = await get_unit_address(ops_test, "am", 0)
    url = f"http://{address}:9093"
    log.info("am public address: %s", url)

    response = urllib.request.urlopen(f"{url}/api/v2/status", data=None, timeout=2.0)
    assert response.code == 200
    assert "versionInfo" in json.loads(response.read())

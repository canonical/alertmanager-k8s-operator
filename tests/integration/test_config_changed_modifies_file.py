#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests change in alertmanager config.

1. Deploy the charm under test with default config and wait for it to become active.
2. Make a config change and expect reload to be triggered.
3. Confirm changes applied.
"""

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


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # deploy charm from local source folder
    await ops_test.model.deploy(  # type: ignore[union-attr]
        charm_under_test, resources=resources, application_name=app_name, trust=True
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)  # type: ignore[union-attr]  # noqa: E501
    assert ops_test.model.applications[app_name].units[0].workload_status == "active"  # type: ignore[union-attr]  # noqa: E501
    assert await is_alertmanager_up(ops_test, app_name)


async def test_update_config(ops_test: OpsTest):
    # Obtain a "before" snapshot of the config from the server.
    client = Alertmanager(await get_unit_address(ops_test, app_name, 0))
    config_from_server_before = client.config()
    # Make sure the defaults is what we expect them to be (this is only a partial check, but an
    # easy one).
    assert "receivers" in config_from_server_before

    def rename_toplevel_receiver(config: dict, new_name: str):
        old_name = config["route"]["receiver"]
        config["route"]["receiver"] = new_name

        for receiver in config["receivers"]:
            if receiver["name"] == old_name:
                receiver["name"] = new_name

    # Modify the default config
    config = config_from_server_before.copy()
    receiver_name = config["route"]["receiver"]
    rename_toplevel_receiver(config, receiver_name * 2)

    await ops_test.model.applications[app_name].set_config({"config_file": yaml.safe_dump(config)})  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=60)  # type: ignore[union-attr]  # noqa: E501

    # Obtain an "after" snapshot of the config from the server.
    config_from_server_after = client.config()
    # Make sure the current config is what we expect it to be (this is only a partial check, but an
    # easy one).
    assert config_from_server_after["receivers"] == config["receivers"]

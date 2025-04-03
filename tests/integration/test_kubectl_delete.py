#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import sh
import yaml
from helpers import is_alertmanager_up
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_deploy_from_local_path(ops_test: OpsTest, charm_under_test):
    """Deploy the charm-under-test."""
    assert ops_test.model
    logger.debug("deploy local charm")

    await ops_test.model.deploy(
        charm_under_test, application_name=app_name, resources=resources, trust=True
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_kubectl_delete_pod(ops_test: OpsTest):
    assert ops_test.model
    assert ops_test.model_name
    pod_name = f"{app_name}-0"

    sh.kubectl.delete.pod(pod_name, namespace=ops_test.model_name)  # pyright: ignore

    application = ops_test.model.applications[app_name]
    assert application
    await ops_test.model.block_until(lambda: len(application.units) > 0)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)

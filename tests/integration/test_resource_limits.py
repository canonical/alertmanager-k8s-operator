#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import subprocess
from pathlib import Path

import pytest
import yaml
from helpers import  is_alertmanager_up
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}

@pytest.mark.abort_on_fail
async def test_resource_limits_apply(ops_test: OpsTest, charm_under_test):
    """Set resource limits and make sure they are applied."""
    logger.info("deploying local charm")
    await ops_test.model.deploy(
        charm_under_test,
        resources=resources,
        application_name=app_name,
        config={"cpu": "300m", "memory": "300M"},
        trust=True
    )
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=300, wait_for_exact_units=1, idle_period=10
    )

    assert await is_alertmanager_up(ops_test, app_name)

    logger.info("upgrade deployed charm with local charm %s", charm_under_test)

    pod = json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "--namespace",
                ops_test.model_name,
                "get",
                "pod",
                "-o",
                "json",
                f"{app_name}-0",
            ],
            text=True,
        )
    )
    container = list(filter(lambda x: x["name"] == "alertmanager", pod["spec"]["containers"]))
    assert container[0]["resources"]["limits"]["cpu"] == "300m"
    assert container[0]["resources"]["limits"]["memory"] == "300M"

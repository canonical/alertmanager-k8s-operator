#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests alertmanager response to related apps being removed and re-related.

1. Deploy the charm under test and a related app, relate them and wait for them to become idle.
2. Remove the relation.
3. Re-add the relation.
4. Remove the related application.
5. Redeploy the related application and add the relation back again.
"""

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import is_alertmanager_up
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}
related_app = "related-app"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms."""
    await asyncio.gather(
        ops_test.model.deploy(
            charm_under_test, resources=resources, application_name=app_name, num_units=2
        ),
        ops_test.model.deploy("ch:prometheus-k8s", application_name=related_app, channel="edge"),
    )

    await ops_test.model.add_relation(app_name, related_app)
    await ops_test.model.wait_for_idle(apps=[app_name, related_app], status="active", timeout=1000)

    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[app_name].remove_relation("alerting", related_app)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_rerelate(ops_test: OpsTest):
    await ops_test.model.add_relation(app_name, related_app)
    await ops_test.model.wait_for_idle(apps=[app_name, related_app], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_remove_related_app(ops_test: OpsTest):
    await ops_test.model.applications[related_app].remove()
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_rerelate_app(ops_test: OpsTest):
    await ops_test.model.deploy("ch:prometheus-k8s", application_name=related_app, channel="edge")
    await ops_test.model.add_relation(app_name, related_app)
    await ops_test.model.wait_for_idle(apps=[app_name, related_app], status="active", timeout=1000)
    assert await is_alertmanager_up(ops_test, app_name)

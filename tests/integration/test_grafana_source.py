import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import grafana_datasource_count
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_fixed

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}

"""We need to ensure that, even if there are multiple units for Alertmanager, only one is shown as a datasouce in Grafana.
To test this, we use this test to simulate multiple units of Alertmanager, and then check that only the leader has the key `grafana_source_host` written to relation data with Grafana.
"""

@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test, deploy the charm from charmhub, and upgrade from path."""
    await asyncio.gather(
        ops_test.model.deploy(charm_under_test, "am", resources=resources, trust=True, num_units=2),
        ops_test.model.deploy("grafana-k8s", "grafana", channel="2/edge", trust=True),
    )
    
    await ops_test.model.add_relation("grafana:grafana-source", "am")
    await ops_test.model.wait_for_idle(apps=["am", "grafana"], status="active")
    
@retry(wait=wait_fixed(10), stop=stop_after_attempt(6))
async def test_grafana_datasources(ops_test: OpsTest):
    # We have 2 units of Alertmanager, but only one datasource should be shown as a Grafana source.
    count = await grafana_datasource_count(ops_test, "grafana")
    assert count == 1
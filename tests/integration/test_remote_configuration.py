#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests remote configuration support in Alertmanager.

0. Deploy `alertmanager-k8s` and `remote-configuration-tester`.
1. Create `remote-configuration` relation.
2. Verify that the configuration provided by `remote-configuration-tester` has been applied in
`alertmanager-k8s`.
"""

import os
import shutil
from pathlib import Path

import helpers
import pytest
import sh
import yaml
from deepdiff import DeepDiff  # type: ignore[import]
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}

TESTER_CHARM_PATH = "./tests/integration/remote_configuration_tester"
TESTER_APP_METADATA = yaml.safe_load(
    Path(os.path.join(TESTER_CHARM_PATH, "charmcraft.yaml")).read_text()
)
TESTER_APP_NAME = TESTER_APP_METADATA["name"]
TESTER_APP_RESOURCES = {
    f"{TESTER_APP_NAME}-image": TESTER_APP_METADATA["resources"][f"{TESTER_APP_NAME}-image"][
        "upstream-source"
    ]
}

TESTER_CHARM_CONFIG = """route:
  receiver: test_receiver
  group_by:
  - alertname
  group_wait: 1234s
  group_interval: 4321s
  repeat_interval: 1111h
receivers:
- name: test_receiver
"""


@pytest.fixture(scope="module")
async def tester_charm(ops_test: OpsTest):
    assert ops_test.model
    _copy_alertmanager_remote_configuration_library_into_tester_charm()
    tester_charm = await ops_test.build_charm(TESTER_CHARM_PATH)
    await ops_test.model.deploy(
        tester_charm,
        resources=TESTER_APP_RESOURCES,
        application_name=TESTER_APP_NAME,
        config={"config_file": TESTER_CHARM_CONFIG},
        trust=True,
    )
    await ops_test.model.wait_for_idle(apps=[TESTER_APP_NAME], status="active", timeout=1000)


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def setup(ops_test: OpsTest, charm_under_test, tester_charm):
    assert ops_test.model
    await ops_test.model.deploy(
        charm_under_test,
        resources=RESOURCES,
        application_name=APP_NAME,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, TESTER_APP_NAME], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_remote_configuration_applied_on_relation_created(ops_test: OpsTest, setup):
    assert ops_test.model
    await ops_test.model.add_relation(
        relation1=f"{APP_NAME}:remote-configuration", relation2=TESTER_APP_NAME
    )
    expected_config = _add_juju_details_to_alertmanager_config(TESTER_CHARM_CONFIG)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        timeout=1000,
        idle_period=5,
    )

    _, actual_config, _ = await helpers.get_alertmanager_config_from_file(
        ops_test=ops_test,
        app_name=APP_NAME,
        container_name="alertmanager",
        config_file_path="/etc/alertmanager/alertmanager.yml",
    )

    assert (
        DeepDiff(
            yaml.safe_load(actual_config),
            yaml.safe_load(expected_config),
            ignore_order=True,
        )
        == {}
    )


@pytest.mark.abort_on_fail
async def test_remote_configuration_file_wrongly_applied(ops_test: OpsTest, setup):
    assert ops_test.model
    sh.juju(  # pyright: ignore
        [
            "config",
            f"{APP_NAME}",
            "-m",
            ops_test.model_name,
            "config_file=tests/integration/am_config.yaml",
        ]
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=1000,
        idle_period=5,
    )


def _copy_alertmanager_remote_configuration_library_into_tester_charm():
    """Ensure that the tester charm uses the current Alertmanager Remote Configuration library."""
    library_path = "lib/charms/alertmanager_k8s/v0/alertmanager_remote_configuration.py"
    install_path = "tests/integration/remote_configuration_tester/" + library_path
    shutil.copyfile(library_path, install_path)


def _add_juju_details_to_alertmanager_config(config: str) -> str:
    juju_details = ["juju_application", "juju_model", "juju_model_uuid"]
    config_dict = yaml.safe_load(config)
    group_by = config_dict["route"]["group_by"]
    group_by.extend(juju_details)
    config_dict["route"]["group_by"] = group_by
    return yaml.safe_dump(config_dict)

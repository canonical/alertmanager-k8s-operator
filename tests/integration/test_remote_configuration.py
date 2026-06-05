#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests remote configuration support in Alertmanager.

0. Deploy `alertmanager-k8s` and `remote-configuration-tester`.
1. Create `remote-configuration` relation.
2. Verify that the configuration provided by `remote-configuration-tester` has been applied in
`alertmanager-k8s`.
3. Set a local config_file and verify alertmanager goes into blocked status.
"""

import os
import shutil
import subprocess
from pathlib import Path

import jubilant
import pytest
import yaml
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import ALERTMANAGER_IMAGE, get_alertmanager_config_from_file

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

APP_NAME = "alertmanager"


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


@pytest.fixture(scope="module")
def tester_charm_path():
    """Build the remote configuration tester charm and return its path."""
    _copy_alertmanager_remote_configuration_library_into_tester_charm()
    result = subprocess.run(
        ["charmcraft", "pack", "--verbose"],
        cwd=TESTER_CHARM_PATH,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"charmcraft pack failed:\n{result.stdout}\n{result.stderr}"
    charms = list(Path(TESTER_CHARM_PATH).glob("*.charm"))
    assert charms, f"No .charm file found in {TESTER_CHARM_PATH} after packing"
    return charms[0]


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path, tester_charm_path: Path):
    juju.deploy(
        str(charm_path),
        APP_NAME,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    juju.deploy(
        f"./{tester_charm_path}",
        TESTER_APP_NAME,
        resources=TESTER_APP_RESOURCES,
        config={"config_file": TESTER_CHARM_CONFIG},
        trust=True,
    )
    juju.wait(
        lambda s: (
            jubilant.all_active(s, APP_NAME, TESTER_APP_NAME)
            and jubilant.all_agents_idle(s, APP_NAME, TESTER_APP_NAME)
        ),
        timeout=1000,
        delay=30,
        successes=3,
    )


def test_remote_configuration_applied(juju):
    juju.integrate(f"{APP_NAME}:remote-configuration", TESTER_APP_NAME)
    juju.wait(
        lambda s: jubilant.all_active(s, APP_NAME) and jubilant.all_agents_idle(s, APP_NAME),
        timeout=1000,
    )

    actual_config = get_alertmanager_config_from_file(
        juju,
        app_name=APP_NAME,
        config_file_path="/etc/alertmanager/alertmanager.yml",
    )
    expected_config = _add_juju_details_to_alertmanager_config(TESTER_CHARM_CONFIG)
    diff = DeepDiff(
        yaml.safe_load(actual_config), yaml.safe_load(expected_config), ignore_order=True
    )
    assert diff == {}, f"Config mismatch: {diff}"


def test_local_config_causes_blocked(juju):
    juju.config(APP_NAME, {"config_file": "tests/integration/am_config.yaml"})
    juju.wait(
        lambda s: all(
            u.workload_status.current == "blocked" for u in s.apps[APP_NAME].units.values()
        ),
        timeout=1000,
        delay=30,
        successes=3,
    )

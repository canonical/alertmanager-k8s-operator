#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager pod deletion resilience."""

import logging
import subprocess
from pathlib import Path

import jubilant
import pytest
from helpers import ALERTMANAGER_IMAGE, is_alertmanager_up

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
    )


def test_kubectl_delete_pod(juju):
    subprocess.run(
        ["kubectl", "delete", "pod", f"{AM_APP}-0", f"--namespace={juju.model}"],
        check=True,
    )
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
    )
    assert is_alertmanager_up(juju, AM_APP)

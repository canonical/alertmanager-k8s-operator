#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager pod deletion resilience."""

import logging
import subprocess
from pathlib import Path

import jubilant
import lightkube
import pytest
import yaml
from helpers import (
    ALERTMANAGER_IMAGE,
    assert_security_context,
    generate_container_securitycontext_map,
    get_pod_names,
    is_alertmanager_up,
)

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)


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
        delay=30,
        successes=3,
    )


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
def test_container_security_context(juju, container_name: str):
    """Test that container security context has the correct UID/GID set."""
    lightkube_client = lightkube.Client()
    pod_name = get_pod_names(juju.model, AM_APP)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        juju.model,
    )


def test_kubectl_delete_pod(juju):
    subprocess.run(
        ["kubectl", "delete", "pod", f"{AM_APP}-0", f"--namespace={juju.model}"],
        check=True,
    )
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)

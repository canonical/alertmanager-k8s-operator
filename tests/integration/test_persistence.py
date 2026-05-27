#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: silence persistence across charm upgrades."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jubilant
import pytest
from helpers import get_unit_address, is_alertmanager_up

from src.alertmanager_client import Alertmanager

logger = logging.getLogger(__name__)

AM_APP = "alertmanager-k8s"


@pytest.mark.juju_setup
def test_deploy(juju):
    juju.deploy(AM_APP, channel="dev/edge", trust=True)
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )


def test_silences_persist_across_upgrade(juju, charm_path: Path):
    address = get_unit_address(juju, AM_APP, 0)
    alertmanager = Alertmanager(f"http://{address}:9093")

    silence_start = datetime.now(timezone.utc)
    silence_end = silence_start + timedelta(minutes=30)
    matchers = [{"name": "alertname", "value": "fake-alert", "isRegex": False}]
    alertmanager.set_silences(matchers, silence_start, silence_end)
    silences_before = alertmanager.get_silences()
    assert silences_before, "No silences found after setting one"

    juju.refresh(AM_APP, path=str(charm_path))
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)

    address = get_unit_address(juju, AM_APP, 0)
    silences_after = Alertmanager(f"http://{address}:9093").get_silences()
    assert silences_after, "No silences found after upgrade"
    assert silences_before == silences_after, (
        f"Silences changed across upgrade: before={silences_before}, after={silences_after}"
    )

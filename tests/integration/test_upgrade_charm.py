#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests alertmanager upgrade with and without relations present.

1. Deploy the charm under test _from charmhub_.
2. Refresh with locally built charm.
3. Add all supported relations.
4. Refresh with locally built charm.
5. Add unit and refresh again (test multi unit upgrade with relations).
"""

import logging
from pathlib import Path

import jubilant
import pytest
from helpers import ALERTMANAGER_IMAGE, is_alertmanager_up

logger = logging.getLogger(__name__)

AM_APP = "alertmanager-k8s"
PROM_APP = "prom"
KARMA_APP = "karma"


@pytest.mark.juju_setup
def test_deploy(juju):
    juju.deploy(AM_APP, channel="dev/edge", trust=True)
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )


def test_upgrade_in_isolation(juju, charm_path: Path):
    juju.refresh(AM_APP, path=str(charm_path), resources={"alertmanager-image": ALERTMANAGER_IMAGE})
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)


def test_upgrade_with_relations(juju, charm_path: Path):
    juju.deploy("prometheus-k8s", PROM_APP, channel="dev/edge", trust=True)
    juju.deploy("karma-k8s", KARMA_APP, channel="dev/edge", trust=True)
    juju.integrate(AM_APP, f"{PROM_APP}:alertmanager")
    juju.integrate(AM_APP, KARMA_APP)
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP, PROM_APP, KARMA_APP)
        and jubilant.all_agents_idle(s, AM_APP, PROM_APP, KARMA_APP),
        timeout=2500,
        delay=30,
        successes=3,
    )

    juju.refresh(AM_APP, path=str(charm_path), resources={"alertmanager-image": ALERTMANAGER_IMAGE})
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP, PROM_APP, KARMA_APP)
        and jubilant.all_agents_idle(s, AM_APP, PROM_APP, KARMA_APP),
        timeout=2500,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)


def test_upgrade_with_multiple_units(juju, charm_path: Path):
    juju.add_unit(AM_APP, num_units=1)
    juju.wait(
        lambda s: len(s.apps[AM_APP].units) == 2
        and jubilant.all_active(s, AM_APP, PROM_APP, KARMA_APP)
        and jubilant.all_agents_idle(s, AM_APP, PROM_APP, KARMA_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )

    juju.refresh(AM_APP, path=str(charm_path), resources={"alertmanager-image": ALERTMANAGER_IMAGE})
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP, PROM_APP, KARMA_APP)
        and jubilant.all_agents_idle(s, AM_APP, PROM_APP, KARMA_APP),
        timeout=2500,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests rescaling.

1. Deploys multiple units of the charm under test and waits for them to become active.
2. Asserts that the elected leader is not unit 0, which is required for this test to be meaningful.
   If unit 0 is elected leader, the test is marked xfail and should be re-run.
3. Scales down to 1 unit (crossing below the current leader) to trigger a leadership change event.
4. Scales up by 2 units and back down by 2 units, verifying health throughout.
"""

import logging
from pathlib import Path

import jubilant
import pytest
from helpers import ALERTMANAGER_IMAGE, get_leader_unit_num, is_alertmanager_up

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"


@pytest.mark.juju_setup
@pytest.mark.xfail
def test_deploy(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        num_units=10,
        trust=True,
    )
    juju.wait(lambda s: jubilant.all_agents_idle(s, AM_APP), timeout=1000, delay=30, successes=3)

    if get_leader_unit_num(juju, AM_APP) == 0:
        pytest.xfail(
            "Elected leader is unit/0. No scale-down can trigger a leadership change. Try re-running."
        )

    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )


@pytest.mark.xfail
def test_scale_down_to_single_unit(juju):
    current = len(juju.status().apps[AM_APP].units)
    juju.remove_unit(AM_APP, num_units=current - 1)
    juju.wait(
        lambda s: len(s.apps[AM_APP].units) == 1
        and jubilant.all_active(s, AM_APP)
        and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)


@pytest.mark.xfail
def test_scale_up_by_two(juju):
    juju.add_unit(AM_APP, num_units=2)
    juju.wait(
        lambda s: len(s.apps[AM_APP].units) == 3
        and jubilant.all_active(s, AM_APP)
        and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)


@pytest.mark.xfail
def test_scale_down_by_two(juju):
    juju.remove_unit(AM_APP, num_units=2)
    juju.wait(
        lambda s: len(s.apps[AM_APP].units) == 1
        and jubilant.all_active(s, AM_APP)
        and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)

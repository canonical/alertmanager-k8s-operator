"""Steps about deploying and operating the Alertmanager charm under test."""

from pathlib import Path

import jubilant
from helpers import ALERTMANAGER_IMAGE, AM_APP
from pytest_bdd import given, when


@given(f'the "{AM_APP}" application is deployed')
def alertmanager_is_deployed(juju: jubilant.Juju, charm_path: Path):
    if AM_APP not in juju.status().apps:
        juju.deploy(
            str(charm_path),
            AM_APP,
            resources={"alertmanager-image": ALERTMANAGER_IMAGE},
            trust=True,
        )
    _wait_settled(juju)


@when(f'the "{AM_APP}" application is refreshed')
def alertmanager_is_refreshed(juju: jubilant.Juju, charm_path: Path):
    juju.refresh(AM_APP, path=str(charm_path))
    _wait_settled(juju)


def _wait_settled(juju: jubilant.Juju) -> None:
    juju.wait(
        lambda s: jubilant.all_active(s) and jubilant.all_agents_idle(s),
        timeout=600,
        delay=30,
        successes=3,
    )

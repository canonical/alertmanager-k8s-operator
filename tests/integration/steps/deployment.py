# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about alertmanager's own deployment: deploying, scaling, refreshing, health.

Every feature runs in its own model (pytest-jubilant's module-scoped `juju` fixture),
so the scenarios of a feature share it. `Given` steps are idempotent: they bring the
model to the state they describe, whatever an earlier scenario left.
"""

import itertools
import subprocess
from pathlib import Path

import jubilant
import pytest
from helpers import (
    ALERTMANAGER_IMAGE,
    AM_APP,
    get_leader_unit_num,
    is_alertmanager_up,
    model_namespace,
)
from pytest_bdd import given, parsers, then, when

# A refresh cannot be undone, so every scenario refreshes an alertmanager of its own.
_charmhub_apps = (f"am-charmhub-{n}" for n in itertools.count())


@pytest.fixture
def app() -> str:
    """The alertmanager application a scenario talks about.

    Scenarios that need a state another scenario of the same feature cannot share
    (e.g. alertmanager serving over TLS) switch to an application of their own,
    through the `target_fixture` of the step that deploys it.
    """
    return AM_APP


def wait_for_active(juju: jubilant.Juju, *apps: str, timeout: float = 1000) -> None:
    juju.wait(
        lambda status: (
            jubilant.all_active(status, *apps) and jubilant.all_agents_idle(status, *apps)
        ),
        timeout=timeout,
        delay=10,
        successes=3,
    )


def deploy_alertmanager(juju: jubilant.Juju, charm_path: Path, app: str) -> None:
    """Deploy the local charm as `app`, unless it is already deployed."""
    if app not in juju.status().apps:
        juju.deploy(
            str(charm_path),
            app,
            resources={"alertmanager-image": ALERTMANAGER_IMAGE},
            trust=True,
        )
    wait_for_active(juju, app)


def scale(juju: jubilant.Juju, charm_path: Path, app: str, units: int) -> None:
    deploy_alertmanager(juju, charm_path, app)
    current = len(juju.status().apps[app].units)
    if units > current:
        juju.add_unit(app, num_units=units - current)
    elif units < current:
        juju.remove_unit(app, num_units=current - units)
    juju.wait(
        lambda status: (
            len(status.apps[app].units) == units
            and jubilant.all_active(status, app)
            and jubilant.all_agents_idle(status, app)
        ),
        timeout=1000,
        delay=10,
        successes=3,
    )


@given("alertmanager is deployed")
def alertmanager_is_deployed(juju: jubilant.Juju, charm_path: Path, app: str):
    deploy_alertmanager(juju, charm_path, app)


@given("alertmanager is deployed from Charmhub", target_fixture="app")
def deployed_from_charmhub(juju: jubilant.Juju) -> str:
    app = next(_charmhub_apps)
    juju.deploy("alertmanager-k8s", app, channel="dev/edge", trust=True)
    wait_for_active(juju, app)
    return app


@given(parsers.re(r"alertmanager has (?P<units>\d+) units?"))
def alertmanager_has_units(juju: jubilant.Juju, charm_path: Path, app: str, units: str):
    scale(juju, charm_path, app, int(units))


@given("the leader is not unit 0")
def leader_is_not_unit_zero(juju: jubilant.Juju, app: str):
    """Move leadership off unit 0, which claims it first, so a scale-down removes the leader.

    Juju has no command to transfer leadership, and on Kubernetes a scale-down always
    removes the highest-numbered units. The unit agent runs as a Pebble service in the
    charm container, so stopping it on the leader lets its lease expire and Juju elects
    another unit. The container's liveness and readiness checks are stopped first:
    otherwise Kubernetes restarts the container, and an agent that is back before the
    lease expires simply renews it.
    """
    if get_leader_unit_num(juju, app) != 0:
        return
    unit = f"{app}/0"
    pebble = "/charm/bin/pebble"
    juju.ssh(
        unit,
        f"{pebble} stop-checks liveness readiness && {pebble} stop container-agent",
        container="charm",
    )
    try:
        juju.wait(
            lambda status: (
                any(u.leader for u in status.apps[app].units.values())
                and not status.apps[app].units[unit].leader
            ),
            timeout=180,
            delay=5,
            successes=3,
        )
    finally:
        juju.ssh(
            unit,
            f"{pebble} start container-agent && {pebble} start-checks liveness readiness",
            container="charm",
        )
    wait_for_active(juju, app)


@when(parsers.re(r"alertmanager is scaled to (?P<units>\d+) units?"))
def alertmanager_is_scaled(juju: jubilant.Juju, charm_path: Path, app: str, units: str):
    scale(juju, charm_path, app, int(units))


@when("alertmanager is refreshed to the local charm")
def alertmanager_is_refreshed(juju: jubilant.Juju, charm_path: Path, app: str):
    juju.refresh(
        app,
        path=str(charm_path),
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
    )
    wait_for_active(juju, app)


@when("the alertmanager pod is deleted")
def delete_pod(juju: jubilant.Juju, app: str):
    namespace = model_namespace(juju)
    subprocess.run(
        ["kubectl", "delete", "pod", f"{app}-0", f"--namespace={namespace}"], check=True
    )
    wait_for_active(juju, app)


@then("alertmanager is healthy")
def alertmanager_is_healthy(juju: jubilant.Juju, app: str):
    """Every application in the model is active, and every alertmanager unit answers its API."""
    wait_for_active(juju, *juju.status().apps)
    assert is_alertmanager_up(juju, app)

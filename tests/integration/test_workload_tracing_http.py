# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager workload tracing over plain HTTP."""

import logging
from pathlib import Path

import jubilant
from helpers import (
    ALERTMANAGER_IMAGE,
    AM_APP,
    TEMPO_APP,
    assert_traces_in_tempo,
    deploy_tempo_stack,
)
from pytest_bdd import given, scenario, then, when

logger = logging.getLogger(__name__)


@scenario("features/workload_tracing_http.feature", "Alertmanager sends traces over plain HTTP")
def test_workload_tracing_http():
    """Alertmanager emits OTLP traces over plain HTTP to Tempo."""


@given("alertmanager and tempo are deployed", target_fixture="deployed_apps")
def deploy_am_and_tempo(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    tempo_apps = deploy_tempo_stack(juju)
    all_apps = {AM_APP} | tempo_apps
    juju.wait(
        lambda status: jubilant.all_active(status, *all_apps)
        and jubilant.all_agents_idle(status, *all_apps),
        timeout=900,
    )
    return all_apps


@when("alertmanager is related to tempo for workload tracing")
def relate_am_to_tempo(juju):
    juju.integrate(f"{AM_APP}:tracing", f"{TEMPO_APP}:tracing")


@then("alertmanager and tempo reach active status")
def wait_for_active(juju, deployed_apps):
    juju.wait(
        lambda status: jubilant.all_active(status, *deployed_apps)
        and jubilant.all_agents_idle(status, *deployed_apps),
        timeout=300,
    )


@then("hitting the healthy endpoint produces a trace in tempo")
def healthy_produces_trace(juju):
    # Trigger a span: curl /-/healthy from inside the alertmanager container.
    juju.exec("curl -sf http://localhost:9093/-/healthy", unit=f"{AM_APP}/0")

    tempo_ip = juju.status().apps[TEMPO_APP].units[f"{TEMPO_APP}/0"].address
    assert_traces_in_tempo(tempo_ip, service_name=AM_APP)


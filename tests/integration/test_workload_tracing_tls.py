# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager workload tracing over TLS."""

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

SSC_APP = "self-signed-certificates"


@scenario("features/workload_tracing.feature", "Alertmanager sends traces over TLS")
def test_workload_tracing_tls():
    """Alertmanager emits OTLP traces over TLS to Tempo, with CA cert verification."""


@given(
    "alertmanager, tempo, and self-signed-certificates are deployed",
    target_fixture="deployed_apps",
)
def deploy_all(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    tempo_apps = deploy_tempo_stack(juju)
    juju.deploy(SSC_APP, SSC_APP, channel="edge")
    all_apps = {AM_APP, SSC_APP} | tempo_apps
    juju.wait(
        lambda status: (
            jubilant.all_active(status, *all_apps) and jubilant.all_agents_idle(status, *all_apps)
        ),
        timeout=900,
        delay=30,
        successes=3,
    )
    return all_apps


@given("alertmanager is related to self-signed-certificates for TLS")
def relate_am_to_ssc(juju, deployed_apps):
    juju.integrate(f"{AM_APP}:certificates", SSC_APP)
    juju.wait(
        lambda status: (
            jubilant.all_active(status, *deployed_apps)
            and jubilant.all_agents_idle(status, *deployed_apps)
        ),
        timeout=300,
        delay=30,
        successes=3,
    )


@when("alertmanager is related to tempo for workload tracing")
def relate_am_to_tempo(juju):
    juju.integrate(f"{AM_APP}:tracing", f"{TEMPO_APP}:tracing")


@then("alertmanager and tempo reach active status")
def wait_for_active(juju, deployed_apps):
    juju.wait(
        lambda status: (
            jubilant.all_active(status, *deployed_apps)
            and jubilant.all_agents_idle(status, *deployed_apps)
        ),
        timeout=300,
        delay=30,
        successes=3,
    )


@then("hitting the healthy endpoint produces a trace in tempo")
def healthy_produces_trace(juju):
    # Use juju.ssh targeting the charm container — curl is not available in the workload container.
    # The TLS certificate SAN is the pod FQDN, not localhost, so we must use the FQDN.
    # The charm container shares the pod network namespace and the FQDN resolves within the cluster.
    am_fqdn = f"{AM_APP}-0.{AM_APP}-endpoints.{juju.model}.svc.cluster.local"
    output = juju.ssh(
        f"{AM_APP}/0",
        f"curl -sf --cacert /usr/local/share/ca-certificates/cos-ca.crt https://{am_fqdn}:9093/-/healthy",
        container="charm",
    )
    assert output.strip(), "Expected non-empty response from alertmanager /-/healthy"

    tempo_ip = juju.status().apps[TEMPO_APP].units[f"{TEMPO_APP}/0"].address
    assert_traces_in_tempo(tempo_ip, service_name=AM_APP)

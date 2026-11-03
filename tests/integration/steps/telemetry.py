# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about the telemetry alertmanager sends: logs to Loki and traces to Tempo."""

import jubilant
import requests
from helpers import TEMPO_APP, assert_traces_in_tempo, get_unit_address, unit_fqdn
from pytest_bdd import then, when
from tenacity import retry, stop_after_attempt, wait_fixed

from steps.relations import COUNTERPARTS, related_apps


@retry(wait=wait_fixed(15), stop=stop_after_attempt(20), reraise=True)
def assert_logs_in_loki(loki_address: str, app: str) -> None:
    response = requests.get(
        f"http://{loki_address}:3100/loki/api/v1/query_range",
        params={"query": f'{{juju_application="{app}"}}'},
    )
    response.raise_for_status()
    assert response.json().get("data", {}).get("result", []), f"No logs from {app}"


@when("a request is made to alertmanager's API")
def request_alertmanager(juju: jubilant.Juju, app: str):
    # curl is only available in the charm container, which shares the pod's network.
    if related_apps(juju, app, "certificates"):
        # The server certificate is issued for the FQDN, not for localhost.
        url = f"https://{unit_fqdn(juju, app, 0)}:9093/-/healthy"
        command = f"curl -sf --cacert /usr/local/share/ca-certificates/cos-ca.crt {url}"
    else:
        command = "curl -sf http://localhost:9093/-/healthy"
    assert juju.ssh(f"{app}/0", command, container="charm").strip()


@then("Loki has logs from alertmanager")
def loki_has_logs(juju: jubilant.Juju, app: str):
    loki_app = COUNTERPARTS["Loki"].app
    assert_logs_in_loki(get_unit_address(juju, loki_app, 0), app)


@then("Tempo has traces from alertmanager")
def tempo_has_traces(juju: jubilant.Juju, app: str):
    assert_traces_in_tempo(get_unit_address(juju, TEMPO_APP, 0), juju_application=app)

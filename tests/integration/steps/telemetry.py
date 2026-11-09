# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about the telemetry alertmanager sends: logs to Loki and traces to Tempo."""

import jubilant
from helpers import unit_fqdn
from observability_clients import Loki, Tempo
from pytest_bdd import then, when
from tenacity import retry, stop_after_delay, wait_fixed

from steps.relations import related_apps

# Telemetry trails the events that produce it, so the steps retry until it arrives.
_until_ingested = retry(wait=wait_fixed(15), stop=stop_after_delay(300), reraise=True)


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
@_until_ingested
def loki_has_logs(loki: Loki, app: str):
    assert loki.has_log_line(f'{{juju_application="{app}"}}'), f"No logs from {app}"


# Workload spans carry the `juju_charm` resource attribute, set through the workload's
# OTEL_RESOURCE_ATTRIBUTES; spans of the charm itself carry `charm_type` instead. Both carry
# `juju_application`, which tells several alertmanager applications in one model apart.


@then("Tempo has workload traces from alertmanager")
@_until_ingested
def tempo_has_workload_traces(tempo: Tempo, app: str):
    query = f'{{ resource.juju_application = "{app}" && resource.juju_charm != nil }}'
    assert tempo.has_traces(query), f"No workload traces from {app}"


@then("Tempo has charm traces from alertmanager")
@_until_ingested
def tempo_has_charm_traces(tempo: Tempo, app: str):
    query = f'{{ resource.juju_application = "{app}" && resource.charm_type != nil }}'
    assert tempo.has_traces(query), f"No charm traces from {app}"

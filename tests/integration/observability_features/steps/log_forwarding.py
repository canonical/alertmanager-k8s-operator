"""Steps about the charm forwarding its workload logs to Loki."""

import jubilant
from observability_clients import Loki
from pytest_bdd import given, then, when
from tenacity import retry, stop_after_delay, wait_fixed

from observability_features.charm import CharmUnderTest
from observability_features.steps._juju import ensure_deployed, ensure_integrated

LOKI_APP = "loki"
LOKI_PORT = 3100


@given("Loki is deployed")
def loki_is_deployed(juju: jubilant.Juju):
    ensure_deployed(juju, LOKI_APP, "loki-k8s", channel="dev/edge")


@given("the charm is integrated with Loki")
@when("the charm is integrated with Loki")
def the_charm_is_integrated_with_loki(juju: jubilant.Juju, charm_under_test: CharmUnderTest):
    ensure_integrated(juju, charm_under_test.app, f"{LOKI_APP}:logging")


@then("Loki has logs from the charm")
def loki_has_logs_from_the_charm(juju: jubilant.Juju, charm_under_test: CharmUnderTest):
    address = juju.status().apps[LOKI_APP].units[f"{LOKI_APP}/0"].address
    _assert_has_logs(
        Loki(url=f"http://{address}:{LOKI_PORT}"),
        query=f'{{juju_application="{charm_under_test.app}"}}',
    )


@retry(stop=stop_after_delay(5 * 60), wait=wait_fixed(15), reraise=True)
def _assert_has_logs(loki: Loki, *, query: str) -> None:
    # Log forwarding is periodic, so the first lines can land after the model settles.
    assert loki.has_log_line(query), f"Loki has no log lines matching {query}"

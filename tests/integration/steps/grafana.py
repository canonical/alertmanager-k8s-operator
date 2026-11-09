# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about what Grafana shows of alertmanager."""

import json
from typing import Callable, List

import jubilant
from observability_clients import Grafana
from pytest_bdd import then
from tenacity import retry, stop_after_delay, wait_fixed


@retry(wait=wait_fixed(10), stop=stop_after_delay(180), reraise=True)
def _datasources_until(grafana: Grafana, predicate: Callable[[List[dict]], bool]) -> List[dict]:
    """Alertmanager's datasources, once they satisfy `predicate` (Grafana updates them lazily)."""
    sources = [s for s in grafana.get_datasources() if s["type"] == "alertmanager"]
    assert predicate(sources), f"Unexpected alertmanager datasources: {sources}"
    return sources


def _ingress_url(juju: jubilant.Juju, app: str) -> str:
    """The URL the ingress provider assigned to `app`, from the app data of its relation."""
    unit = json.loads(juju.cli("show-unit", f"{app}/0", "--format=json"))[f"{app}/0"]
    (relation,) = (r for r in unit["relation-info"] if r["endpoint"] == "ingress")
    return json.loads(relation["application-data"]["ingress"])["url"]


@then("Grafana has a single datasource for alertmanager")
def single_datasource(grafana: Grafana):
    _datasources_until(grafana, lambda sources: len(sources) == 1)


@then("the datasource is served by alertmanager's Kubernetes service")
def datasource_at_service(grafana: Grafana, app: str):
    _datasources_until(
        grafana,
        lambda sources: (
            len(sources) == 1 and sources[0]["url"].startswith(f"http://{app}-endpoints")
        ),
    )


@then("the datasource is served by alertmanager's ingress")
def datasource_at_ingress(juju: jubilant.Juju, grafana: Grafana, app: str):
    ingress_url = _ingress_url(juju, app)
    _datasources_until(
        grafana,
        lambda sources: len(sources) == 1 and sources[0]["url"].startswith(ingress_url),
    )

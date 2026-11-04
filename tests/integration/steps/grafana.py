# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about what Grafana shows of alertmanager."""

import jubilant
from helpers import grafana_datasources
from pytest_bdd import parsers, then
from tenacity import retry, stop_after_delay, wait_fixed

from steps.relations import COUNTERPARTS


@retry(wait=wait_fixed(10), stop=stop_after_delay(180), reraise=True)
def datasources_until(juju: jubilant.Juju, predicate) -> list:
    """Grafana's datasources, once they satisfy `predicate` (Grafana updates them lazily)."""
    sources = grafana_datasources(juju, COUNTERPARTS["Grafana"].app)
    assert predicate(sources), f"Unexpected datasources: {sources}"
    return sources


@then(
    parsers.re(
        r"Grafana has one datasource for alertmanager, (?P<negation>not )?at its"
        r" Kubernetes service URL"
    )
)
def one_datasource_at_service_url(juju: jubilant.Juju, app: str, negation: str):
    service_url = f"http://{app}-endpoints"
    at_service = not negation
    datasources_until(
        juju,
        lambda sources: (
            len(sources) == 1 and sources[0]["url"].startswith(service_url) == at_service
        ),
    )

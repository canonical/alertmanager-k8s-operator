# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps relating alertmanager to the charms it integrates with."""

from dataclasses import dataclass
from typing import Callable, Dict, List

import jubilant
from helpers import TEMPO_APP, deploy_tempo_stack
from pytest_bdd import given, parsers, when

from steps.deployment import wait_for_active


def from_charmhub(
    charm: str, channel: str, trust: bool = True
) -> Callable[[jubilant.Juju, str], object]:
    def deploy(juju: jubilant.Juju, app: str) -> None:
        juju.deploy(charm, app, channel=channel, trust=trust)

    return deploy


@dataclass(frozen=True)
class Counterpart:
    """A charm alertmanager relates to, under the name the feature files use for it."""

    app: str
    deploy: Callable[[jubilant.Juju, str], object]
    timeout: float = 600


COUNTERPARTS: Dict[str, Counterpart] = {
    "a CA": Counterpart("ca", from_charmhub("self-signed-certificates", "edge", trust=False)),
    "Grafana": Counterpart("grafana", from_charmhub("grafana-k8s", "dev/edge")),
    "Karma": Counterpart("karma", from_charmhub("karma-k8s", "dev/edge"), timeout=2500),
    "Loki": Counterpart("loki", from_charmhub("loki-k8s", "dev/edge")),
    "Prometheus": Counterpart("prom", from_charmhub("prometheus-k8s", "dev/edge"), timeout=2500),
    # Tempo is a coordinator with workers and object storage, deployed as a stack.
    "Tempo": Counterpart(TEMPO_APP, lambda juju, _: deploy_tempo_stack(juju), timeout=900),
    "Traefik": Counterpart("traefik", from_charmhub("traefik-k8s", "edge")),
}


def related_apps(juju: jubilant.Juju, app: str, endpoint: str) -> List[str]:
    return [r.related_app for r in juju.status().apps[app].relations.get(endpoint, [])]


def relate_to(juju: jubilant.Juju, app: str, name: str, endpoint: str) -> None:
    """Relate `app` over `endpoint` to the named counterpart, deploying it if needed."""
    counterpart = COUNTERPARTS[name]
    if counterpart.app not in juju.status().apps:
        counterpart.deploy(juju, counterpart.app)
    if counterpart.app not in related_apps(juju, app, endpoint):
        juju.integrate(f"{app}:{endpoint}", counterpart.app)
    # Every application in the model settles, including the rest of a deployed stack.
    wait_for_active(juju, *juju.status().apps, timeout=counterpart.timeout)


@given(parsers.parse('alertmanager is related to {name} over "{endpoint}"'))
@when(parsers.parse('alertmanager is related to {name} over "{endpoint}"'))
def alertmanager_is_related(juju: jubilant.Juju, app: str, name: str, endpoint: str):
    relate_to(juju, app, name, endpoint)


@given("alertmanager has no ingress relation")
def no_ingress(juju: jubilant.Juju, app: str):
    traefik_app = COUNTERPARTS["Traefik"].app
    if traefik_app in related_apps(juju, app, "ingress"):
        juju.remove_relation(f"{app}:ingress", traefik_app)
        juju.wait(
            lambda status: (
                not status.apps[app].relations.get("ingress")
                and jubilant.all_active(status, *status.apps)
            ),
            timeout=600,
            delay=10,
            successes=3,
        )

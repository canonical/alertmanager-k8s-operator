# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures giving the steps an API client for each workload alertmanager relates to."""

import base64

import jubilant
import pytest
from helpers import get_unit_address, grafana_password
from observability_clients import Grafana, Loki, Tempo

from steps.relations import COUNTERPARTS


def _url(juju: jubilant.Juju, name: str, port: int) -> str:
    return f"http://{get_unit_address(juju, COUNTERPARTS[name].app, 0)}:{port}"


@pytest.fixture
def grafana(juju: jubilant.Juju) -> Grafana:
    password = grafana_password(juju, COUNTERPARTS["Grafana"].app)
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return Grafana(url=_url(juju, "Grafana", 3000), headers={"Authorization": f"Basic {token}"})


@pytest.fixture
def loki(juju: jubilant.Juju) -> Loki:
    return Loki(url=_url(juju, "Loki", 3100))


@pytest.fixture
def tempo(juju: jubilant.Juju) -> Tempo:
    return Tempo(url=_url(juju, "Tempo", 3200))

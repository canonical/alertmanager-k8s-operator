# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the workload's scheme is reflected in the pebble command and in relation data.

This feature spans:
- manifest generation (pebble layer)
- schema generation (alertmanager_dispatch provider)

The alertmanager server can serve over HTTP or HTTPS. The requirer side of the relation may be
designed to take URL parts rather than a full URL. Prometheus takes URL parts and would need to
generate its "alertmanagers" config section differently depending on the scheme.
"""

import dataclasses
import json

import pytest
from helpers import cli_arg
from ops.testing import Context, Relation, State


@pytest.fixture
def alerting_relation() -> Relation:
    return Relation("alerting", remote_app_name="prom")


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
def test_pebble_command_serves_over_http_without_a_certificates_relation(
    context: Context, base_state: State, leader: bool, fqdn, port
):
    # GIVEN a charm with no "certificates" relation
    state_in = dataclasses.replace(base_state, leader=leader)

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the workload is served over http at its own fqdn
    assert cli_arg(state, "--web.external-url") == f"http://{fqdn}:{port}"


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
def test_alerting_relation_data_advertises_http_without_a_certificates_relation(
    context: Context, base_state: State, alerting_relation, leader: bool, fqdn, port
):
    # GIVEN a charm with an "alerting" relation but no "certificates" relation
    state_in = dataclasses.replace(
        base_state, leader=leader, relations=[*base_state.relations, alerting_relation]
    )

    # WHEN the consumer joins
    state = context.run(
        context.on.relation_joined(alerting_relation, remote_unit=0), state_in
    )

    # THEN the charm advertises itself over http at its own fqdn
    local_unit_data = state.get_relation(alerting_relation.id).local_unit_data
    assert local_unit_data["public_address"] == f"{fqdn}:{port}"
    assert local_unit_data["scheme"] == "http"


@pytest.mark.xfail(
    reason=(
        "The remote databag needs a certificate matching the CSR alertmanager generates on "
        "certificates-relation-joined; without that forward reference the tls_certificates lib "
        "ignores the certificate and no handler fires."
    )
)
@pytest.mark.parametrize("fqdn", ["localhost"])
def test_pebble_command_serves_over_https_with_a_certificates_relation(
    context: Context, base_state: State, fqdn, port
):
    # GIVEN a charm related to a CA that has issued it a certificate
    certificates = Relation(
        "certificates",
        remote_app_name="ca",
        remote_app_data={
            "certificates": json.dumps(
                [
                    {
                        "certificate": "placeholder",
                        "certificate_signing_request": "placeholder",
                        "ca": "placeholder",
                        "chain": ["first", "second"],
                    }
                ]
            )
        },
    )
    state_in = dataclasses.replace(
        base_state, relations=[*base_state.relations, certificates]
    )

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(certificates), state_in)

    # THEN the workload is served over https
    assert cli_arg(state, "--web.external-url") == f"https://{fqdn}:{port}"

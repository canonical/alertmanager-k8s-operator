# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: The workload's scheme is reflected in the pebble command and in relation data.

This feature spans:
- manifest generation (pebble layer)
- schema generation (alertmanager_dispatch provider)

The alertmanager server can serve over HTTP or HTTPS. The requirer side of the relation may be
design to take URL parts rather than a full URL. Prometheus takes URL parts and would need to
generate its "alertmanagers" config section differently depending on the scheme.
"""

import json
from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Relation, State


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
class TestServerScheme:
    """Scenario: The workload is deployed to operate in HTTP mode, then switched to HTTPS."""

    @pytest.fixture
    def initial_state(self, context, fqdn, leader) -> State:  # pyright: ignore
        """This is the initial state for this test class."""
        # GIVEN an isolated alertmanager charm after the startup sequence is complete

        # No "tls-certificates" relation, no config options
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = begin_with_initial_hooks_isolated(context, leader=leader)

            # Add relation
            prom_rel = Relation("alerting", relation_id=10)
            state = add_relation_sequence(context, state, prom_rel)
            yield state  # keep the patch active for so long as this fixture is needed  # pyright:ignore

    def test_initial_state_has_http_scheme_in_pebble_layer(self, context, initial_state, fqdn):
        # THEN the pebble command has 'http' and the correct hostname in the 'web.external-url' arg
        container = initial_state.get_container("alertmanager")
        command = container.layers["alertmanager"].services["alertmanager"].command
        assert f"--web.external-url=http://{fqdn}:9093" in command

    @pytest.mark.xfail
    def test_pebble_layer_scheme_becomes_https_if_tls_relation_added(
        self, context, initial_state, fqdn
    ):
        # WHEN a tls_certificates relation joins
        ca = Relation(
            "certificates",
            relation_id=100,
            remote_app_data={
                "certificates": json.dumps(
                    [
                        {
                            # fixme: the problem is: instead of "placeholder" here we need a forward ref to the
                            #  CSR that AM will generate on certificates_relation_joined.
                            #  Otherwise, as it stands, charms/tls_certificates_interface/v2/tls_certificates.py:1336 will not find
                            #  this csr and ignore it. Hence no handlers are triggered.
                            "certificate": "placeholder",
                            "certificate_signing_request": "placeholder",
                            "ca": "placeholder",
                            "chain": ["first", "second"],
                        }
                    ]
                )
            },
        )  # TODO figure out how to easily figure out structure of remote data
        state = add_relation_sequence(context, initial_state, ca)
        # TODO figure out why relation-changed observer in tls_certificates is not being called

        # THEN the pebble command has 'https' in the 'web.external-url' arg
        container = state.get_container("alertmanager")
        command = container.layers["alertmanager"].services["alertmanager"].command
        assert f"--web.external-url=https://{fqdn}:9093" in command

    def test_alerting_relation_data_scheme(self, initial_state, fqdn):
        # FIXME: should rely on interface tests for this kind of test.

        # THEN the "alerting" relation data has 'http' and the correct hostname
        relation = initial_state.get_relations("alerting")[0]
        assert relation.local_unit_data["public_address"] == f"{fqdn}:9093"
        assert relation.local_unit_data["scheme"] == "http"

        # WHEN a tls_certificates relation joins
        # TODO

        # THEN the "alerting" relation data has 'http' and the correct hostname
        # TODO

    def test_self_monitoring_scrape_job_scheme(self, fqdn, leader):
        # TODO
        pass

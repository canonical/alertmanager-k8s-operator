# Feature: Blog
#     A site where you can publish your articles.
#
#     Scenario: Publishing the article
#         Given I'm an author user
#         And I have an article
#
#         When I go to the article page
#         And I press the publish button
#
#         Then I should not see the error message
#         And the article should be published  # Note: will query the database


# https://stackoverflow.com/a/62176555/3516684


# | Gherkin element | pytest artifact |
# |-----------------|-----------------|
# | Feature         | *.py            |
# | Scenario        | Class           |
# | Step            | Method          |


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
from helpers import begin_with_initial_hooks_isolated
from scenario import Relation, State


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
class TestServerScheme:
    """Scenario: The workload is deployed to operate in HTTP mode, then switched to HTTPS."""

    @pytest.fixture
    def post_startup(self, context, fqdn, leader) -> State:
        # No "tls-certificates" relation, no config options
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = begin_with_initial_hooks_isolated(context, leader=leader)

            # Add 3 relations
            prom_rels = [Relation("alerting", relation_id=rel_id) for rel_id in (10, 11)]
            for prom_rel in prom_rels:
                state.relations.append(prom_rel)
                state = context.run(prom_rel.created_event, state)
                state = context.run(prom_rel.joined_event, state)
                state = context.run(prom_rel.changed_event, state)

            return state

    def test_pebble_layer_scheme(self, context, post_startup, fqdn):
        # GIVEN an isolated alertmanager charm after the startup sequence is complete
        state = post_startup

        # THEN the pebble command has 'http' and the correct hostname in the 'web.external-url' arg
        container = state.get_container("alertmanager")
        command = container.layers["alertmanager"].services["alertmanager"].command
        assert f"--web.external-url=http://{fqdn}:9093" in command

        # WHEN a tls_certificates relation joins
        ca = Relation(
            "certificates",
            relation_id=100,
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
        )  # TODO figure out how to easily figure out structure of remote data
        state.relations.append(ca)
        # TODO add a context.add_relation() helper?
        state = context.run(ca.created_event, state)
        state = context.run(ca.joined_event, state)
        state = context.run(ca.changed_event, state)
        # TODO figure out why relation-changed observer in tls_certificates is not being called

        # THEN the pebble command has 'https' in the 'web.external-url' arg
        container = state.get_container("alertmanager")
        command = container.layers["alertmanager"].services["alertmanager"].command
        assert f"--web.external-url=https://{fqdn}:9093" in command

    def test_relation_data_scheme(self, post_startup, fqdn):
        # GIVEN an isolated alertmanager charm after the startup sequence is complete
        state = post_startup

        # THEN the "alerting" relation data has 'http' and the correct hostname
        relation = state.get_relations("alerting")[0]
        assert relation.local_unit_data["public_address"] == f"{fqdn}:9093"
        assert relation.local_unit_data["scheme"] == "http"

        # WHEN a tls_certificates relation joins
        # TODO

        # THEN the "alerting" relation data has 'http' and the correct hostname
        # TODO

    def test_self_monitoring_scrape_job_scheme(self):
        # TODO
        pass

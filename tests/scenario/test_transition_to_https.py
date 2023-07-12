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
from helpers import begin_with_initial_hooks_isolated, add_relation_sequence
from scenario import Relation, State, Context


@pytest.fixture(params=["localhost", "am-0.endpoints.cluster.local"])
def fqdn(request):
    yield request.param


@pytest.fixture(autouse=True)
def patch_fqdn(fqdn):
    with patch("socket.getfqdn", new=lambda *args: fqdn):
        yield


@pytest.fixture(params=[True, False])
def is_leader(request):
    yield request.param


@pytest.fixture
def initial_state(context, is_leader):
    """An isolated alertmanager instance after the startup sequence."""
    return begin_with_initial_hooks_isolated(context, leader=is_leader)


@pytest.fixture
def state_with_alerting_relation(initial_state, context, is_leader):
    """Alertmanager after an alerting relation has been added."""
    return add_relation_sequence(context, initial_state, Relation("alerting", relation_id=10))


@pytest.fixture
def state_with_tls_relation(initial_state, context, is_leader):
    """Alertmanager after a tls relation has been added."""
    return add_relation_sequence(
        context, initial_state, Relation(
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
        )  # TODO figure out how to easily figure out the process of figuring out the structure of remote data
    )


def test_initial_state_has_http_scheme_in_pebble_layer(context, initial_state, fqdn):
    # check that the pebble command has 'http' and the correct hostname in the 'web.external-url' arg
    container = initial_state.get_container("alertmanager")
    command = container.layers["alertmanager"].services["alertmanager"].command
    assert f"--web.external-url=http://{fqdn}:9093" in command


def test_state_after_tls_added_has_https_scheme(context, state_with_tls_relation, fqdn):
    # WHEN a tls_certificates relation joins
    # TODO figure out why relation-changed observer in tls_certificates is not being called

    # THEN the pebble command has 'https' in the 'web.external-url' arg
    container = state_with_tls_relation.get_container("alertmanager")
    command = container.layers["alertmanager"].services["alertmanager"].command
    assert f"--web.external-url=https://{fqdn}:9093" in command


def test_alerting_relation_data_scheme(state_with_alerting_relation, fqdn):
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

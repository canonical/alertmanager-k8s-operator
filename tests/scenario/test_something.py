
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

import pytest
from unittest.mock import patch
from scenario import Container, State


@pytest.mark.parametrize(
    ("fqdn", ),
    [
        ("localhost", ),
        ("foo.bar", ),
        ("am-0.endpoints.cluster.local", ),
    ],
)
class TestHTTP:
    """Scenario: The workload is deployed to operate in HTTP mode."""

    @pytest.fixture
    def fixt(self):
        # No "tls-certificates" relation, no config options
        # TODO return charm, context, whatever needed for the next steps
        pass

    def test_pebble_layer_is_http(self, context, fqdn):
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            # TODO why "config_file": "" is needed?
            state_out = context.run("update-status", State(config={"config_file": ""}, containers=[Container("alertmanager", can_connect=True)]))
            container = state_out.get_container("alertmanager")
            command = container.layers["alertmanager"].services["alertmanager"].command
            assert f"--web.external-url=http://{fqdn}:9093" in command

    def test_relation_data_is_http(self, fqdn):
        pass

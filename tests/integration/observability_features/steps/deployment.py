"""Steps about the charm under test itself."""

import jubilant
from pytest_bdd import given

from observability_features.charm import CharmUnderTest
from observability_features.steps._juju import wait_settled


@given("the charm is deployed")
def the_charm_is_deployed(juju: jubilant.Juju, charm_under_test: CharmUnderTest):
    if charm_under_test.app not in juju.status().apps:
        charm_under_test.deploy(juju)
    wait_settled(juju, charm_under_test.app)

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager serves its API over TLS."""

import jubilant
from observability_features import CharmUnderTest, feature
from pytest_bdd import scenarios, when

scenarios(feature("tls.feature"), "features/tls.feature")


@when("the charm is refreshed")
def the_charm_is_refreshed(juju: jubilant.Juju, charm_under_test: CharmUnderTest):
    juju.refresh(charm_under_test.app, path=charm_under_test.charm)
    juju.wait(
        lambda s: jubilant.all_active(s) and jubilant.all_agents_idle(s),
        timeout=600,
        delay=30,
        successes=3,
    )

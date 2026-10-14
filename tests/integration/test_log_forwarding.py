# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager forwards its logs to Loki."""

from observability_features import feature
from pytest_bdd import scenarios

scenarios(feature("log_forwarding.feature"))

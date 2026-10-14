# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager forwards its logs to Loki."""

from pytest_bdd import scenarios

scenarios("features/log_forwarding.feature")

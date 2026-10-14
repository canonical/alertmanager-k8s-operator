# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager serves its API over TLS."""

from pytest_bdd import scenarios

scenarios("features/tls.feature")

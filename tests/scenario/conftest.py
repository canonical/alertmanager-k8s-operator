# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from alertmanager import WorkloadManager
from charm import AlertmanagerCharm
from scenario import Context


def tautology(*_, **__) -> bool:
    return True


@pytest.fixture
def alertmanager_charm():
    with patch("charm.KubernetesServicePatch"), patch(
        "lightkube.core.client.GenericSyncClient"
    ), patch.multiple(
        "charm.KubernetesComputeResourcesPatch",
        _namespace="test-namespace",
        _patch=tautology,
        is_ready=tautology,
    ), patch.object(
        WorkloadManager, "check_config", lambda *a, **kw: ("ok", "")
    ), patch.object(
        WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0")
    ):
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)

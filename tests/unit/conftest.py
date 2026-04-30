from unittest.mock import patch

import pytest
from ops.testing import Context

from src.alertmanager import WorkloadManager
from src.charm import AlertmanagerCharm


def tautology(*_, **__) -> bool:
    return True


@pytest.fixture(autouse=True)
def alertmanager_charm():
    with patch("lightkube.core.client.GenericSyncClient"), patch.multiple(
        "charm.KubernetesComputeResourcesPatch",
        _namespace="test-namespace",
        _patch=tautology,
        is_ready=tautology,
    ), patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", "")), patch.object(
        WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0")
    ), patch("subprocess.run"):
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)

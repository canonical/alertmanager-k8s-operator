from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from ops.testing import Context

from src.alertmanager import WorkloadManager
from src.charm import AlertmanagerCharm


@pytest.fixture(autouse=True)
def patch_buffer_file_for_charm_tracing(tmp_path):
    with patch(
        "charms.tempo_coordinator_k8s.v0.charm_tracing.BUFFER_DEFAULT_CACHE_FILE_NAME",
        str(tmp_path / "foo.json"),
    ):
        yield


@pytest.fixture(autouse=True)
def silence_tracing():
    with charm_tracing_disabled():
        yield


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

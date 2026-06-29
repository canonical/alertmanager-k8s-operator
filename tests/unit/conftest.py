from contextlib import ExitStack
from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from ops.testing import Context

from alertmanager import WorkloadManager
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
    with ExitStack() as stack:
        stack.enter_context(patch("lightkube.core.client.GenericSyncClient"))
        stack.enter_context(
            patch.multiple(
                "charm.KubernetesComputeResourcesPatch",
                _namespace="test-namespace",
                _patch=tautology,
                is_ready=tautology,
            )
        )
        stack.enter_context(
            patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", ""))
        )
        stack.enter_context(patch.object(WorkloadManager, "reload", lambda *a, **kw: None))
        stack.enter_context(
            patch.object(
                WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0")
            )
        )
        stack.enter_context(patch("subprocess.run"))
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)

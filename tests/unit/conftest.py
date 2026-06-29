from contextlib import ExitStack
from unittest.mock import patch

import pytest
from ops.testing import Context

from alertmanager import WorkloadManager
from src.charm import AlertmanagerCharm


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

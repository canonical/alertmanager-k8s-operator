from unittest.mock import patch

import pytest
from alertmanager import WorkloadManager
from charm import AlertmanagerCharm
from ops.model import Container as OpsContainer
from scenario import Context


def tautology(*_, **__) -> bool:
    return True


class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self):
        return "version 0.1.0", ""


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
        OpsContainer, "exec", new=FakeProcessVersionCheck
    ):
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)

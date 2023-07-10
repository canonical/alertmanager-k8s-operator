from unittest.mock import patch

import pytest
from charm import AlertmanagerCharm
from scenario import Context, State, Container, PeerRelation
from alertmanager import WorkloadManager
from ops.model import Container as OpsContainer

def tautology(*_, **__) -> bool:
    return True

class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self):
        return ("version 0.1.0", "")


@pytest.fixture

def alertmanager_charm():
    with patch("charm.KubernetesServicePatch"), patch("lightkube.core.client.GenericSyncClient"), patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=tautology,
    is_ready=tautology,
), patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", "")), patch.object(OpsContainer, "exec", new=FakeProcessVersionCheck):
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)


@pytest.fixture(scope="function")
def state_after_begin_with_initial_hooks_isolated(context: Context):
    leader = True  # TODO: parametrize

    container = Container("alertmanager", can_connect=False)
    state = State(config={"config_file": ""}, containers=[container])
    peer_rel = PeerRelation("replicas")

    state = context.run("install", state)

    state = state.replace(relations=[peer_rel])
    state = context.run(peer_rel.created_event, state)

    if leader:
        state = state.replace(leader=True)
        state = context.run("leader-elected", state)
    else:
        state = state.replace(leader=False)
        state = context.run("leader-settings-changed", state)

    state = context.run("config-changed", state)

    # state = state.with_can_connect("alertmanger")
    container = container.replace(can_connect=True)
    state = state.replace(containers=[container])
    state = context.run(container.pebble_ready_event, state)

    state = context.run("start", state)

    return state

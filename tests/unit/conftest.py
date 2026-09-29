from contextlib import ExitStack
from unittest.mock import patch

import pytest
from ops.testing import Container, Context, Exec, PeerRelation, State

from alertmanager import WorkloadManager
from src.charm import AlertmanagerCharm

FQDN = "fqdn"


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


@pytest.fixture
def fqdn():
    """The hostname the charm sees. Override in a test module to vary it."""
    return FQDN


@pytest.fixture(autouse=True)
def patch_fqdn(fqdn):
    with patch("socket.getfqdn", new=lambda *args: fqdn):
        yield


@pytest.fixture
def port(alertmanager_charm):
    return alertmanager_charm._ports.api


@pytest.fixture
def container() -> Container:
    """A ready alertmanager container."""
    return Container(
        "alertmanager",
        can_connect=True,
        execs={
            Exec(["update-ca-certificates", "--fresh"]),
            Exec(
                ["alertmanager", "--version"],
                stdout="alertmanager, version 0.23.0 (branch: HEAD, ...",
            ),
            Exec(["/usr/bin/amtool", "check-config", "/etc/alertmanager/alertmanager.yml"]),
        },
    )


@pytest.fixture
def peer_relation() -> PeerRelation:
    return PeerRelation("replicas")


@pytest.fixture
def base_state(container, peer_relation) -> State:
    """A leader alertmanager unit with a ready container and its peer relation.

    The charm reconciles its entire world on every event, so a single event run
    against this state is enough to exercise startup behaviour.
    """
    return State(
        leader=True,
        config={"config_file": ""},
        containers=[container],
        relations=[peer_relation],
    )

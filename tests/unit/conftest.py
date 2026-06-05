import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ops.testing import Context

from alertmanager import WorkloadManager
from alertmanager_client import Alertmanager
from charm import AlertmanagerCharm


def tautology(*_, **__) -> bool:
    return True


# Path to the charm root directory
CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(autouse=True)
def suppress_noisy_loggers():
    """Suppress expected warnings from charm libraries during unit tests."""
    loggers_to_suppress = [
        "charms.loki_k8s.v1.loki_push_api",
    ]
    original_levels = {}
    for logger_name in loggers_to_suppress:
        logger = logging.getLogger(logger_name)
        original_levels[logger_name] = logger.level
        logger.setLevel(logging.ERROR)

    yield

    for logger_name, level in original_levels.items():
        logging.getLogger(logger_name).setLevel(level)


def _resolve_dir_against_charm_path_mock(charm, *path_elements):
    """Mock that resolves paths against the real charm root directory."""
    return str(CHARM_ROOT.joinpath(*path_elements))


def _mock_alertmanager_api(*args, **kwargs) -> MagicMock:
    """Create a mock Alertmanager API client that returns successful responses.

    The config() method returns incrementing values to avoid "config remained the same"
    warnings during reload verification.
    """
    mock_api = MagicMock(spec=Alertmanager)
    mock_api.reload.return_value = True
    mock_api.status.return_value = {
        "cluster": {"peers": [], "status": "disabled"},
        "config": {"original": "global: {}"},
        "uptime": "2021-08-31T14:15:31.613Z",
        "versionInfo": {"version": "0.27.0"},
    }
    # Use side_effect to return different configs on each call
    # This prevents "config remained the same after a reload" warnings
    call_count = {"n": 0}

    def incrementing_config():
        call_count["n"] += 1
        return {"global": {}, "version": call_count["n"]}

    mock_api.config.side_effect = incrementing_config
    return mock_api


@pytest.fixture(autouse=True)
def alertmanager_charm():
    with (
        patch("lightkube.core.client.GenericSyncClient"),
        patch.multiple(
            "charm.KubernetesComputeResourcesPatch",
            _namespace="test-namespace",
            _patch=tautology,
            is_ready=tautology,
        ),
        patch.object(WorkloadManager, "check_config", lambda *a, **kw: ("ok", "")),
        patch.object(WorkloadManager, "_alertmanager_version", property(lambda *_: "0.0.0")),
        # Mock the Alertmanager client constructor to return a mock that succeeds
        patch("alertmanager.Alertmanager", _mock_alertmanager_api),
        patch("subprocess.run"),
        # Mock grafana dashboard path resolution to use the real charm root
        patch(
            "charms.grafana_k8s.v0.grafana_dashboard._resolve_dir_against_charm_path",
            _resolve_dir_against_charm_path_mock,
        ),
    ):
        yield AlertmanagerCharm


@pytest.fixture(scope="function")
def context(alertmanager_charm):
    return Context(charm_type=alertmanager_charm)

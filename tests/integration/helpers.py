# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing integration tests."""

import json
import logging
import subprocess
import urllib.request
from pathlib import Path
from typing import Set
from urllib.parse import urlparse

import requests
import yaml
from jubilant import Juju
from requests.auth import HTTPBasicAuth
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

_METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
ALERTMANAGER_IMAGE: str = _METADATA["resources"]["alertmanager-image"]["upstream-source"]

AM_APP = "alertmanager"
TEMPO_APP = "tempo"
TEMPO_WORKER_APP = "tempo-worker"
SEAWEED_APP = "seaweed"
TEMPO_QUERY_PORT = 3200


def get_unit_address(juju: Juju, app_name: str, unit_num: int) -> str:
    """Return the IP address of a specific unit."""
    return juju.status().apps[app_name].units[f"{app_name}/{unit_num}"].address


def is_alertmanager_up(juju: Juju, app_name: str) -> bool:
    """Return True if all alertmanager units respond to the status endpoint."""
    app = juju.status().apps.get(app_name)
    if not app:
        return False
    return all(_unit_responds(unit.address) for unit in app.units.values())


def _unit_responds(address: str) -> bool:
    try:
        resp = urllib.request.urlopen(f"http://{address}:9093/api/v2/status", timeout=2.0)
        return resp.code == 200 and "versionInfo" in json.loads(resp.read())
    except Exception:
        return False


def get_leader_unit_num(juju: Juju, app_name: str) -> int:
    """Return the unit number of the current leader, or -1 if none found."""
    app = juju.status().apps.get(app_name)
    if not app:
        return -1
    for unit_name, unit in app.units.items():
        if unit.leader:
            return int(unit_name.split("/")[1])
    return -1


def get_alertmanager_config_from_file(
    juju: Juju,
    app_name: str,
    config_file_path: str,
) -> str:
    """Read a file from inside an alertmanager container and return its content."""
    return juju.ssh(f"{app_name}/0", f"cat {config_file_path}", container="alertmanager")


def grafana_password(juju: Juju, app_name: str) -> str:
    """Return the Grafana admin password."""
    task = juju.run(f"{app_name}/leader", "get-admin-password")
    return task.results["admin-password"]


def grafana_datasources(juju: Juju, app_name: str) -> list:
    """Return the list of datasources configured in Grafana."""
    address = get_unit_address(juju, app_name, 0)
    url = f"http://{address}:3000/api/datasources"
    admin_password = grafana_password(juju, app_name)
    response = requests.get(url, auth=HTTPBasicAuth("admin", admin_password))
    response.raise_for_status()
    return response.json()


def curl(*, cert_dir: Path, cert_path: Path, ip_addr: str, mock_url: str) -> str:
    """Run curl with a CA certificate bundle and return stdout.

    Raises AssertionError if curl exits with a non-zero return code.
    """
    p = urlparse(mock_url)
    cmd = [
        "curl",
        "-s",
        "--fail-with-body",
        "--resolve",
        f"{p.hostname}:{p.port or 443}:{ip_addr}",
        "--capath",
        str(cert_dir),
        "--cacert",
        str(cert_path),
        mock_url,
    ]
    logger.info("cURL command: '%s'", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(
        "%s: rc=%s stdout=%s stderr=%s",
        mock_url,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    assert result.returncode == 0, (
        f"curl exited with rc={result.returncode} for {mock_url}; "
        "non-zero return code means curl encountered a >= 400 HTTP code"
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Jubilant / workload-tracing helpers
# ---------------------------------------------------------------------------


def deploy_tempo_stack(juju: Juju) -> Set[str]:
    """Deploy tempo-coordinator + tempo-worker + seaweedfs and wire their integrations.

    Returns the set of application names that were deployed so callers can
    include them in ``juju.wait`` calls.
    """
    juju.deploy("seaweedfs-k8s", SEAWEED_APP, channel="edge", trust=True)
    juju.deploy("tempo-coordinator-k8s", TEMPO_APP, channel="dev/edge", trust=True)
    juju.deploy("tempo-worker-k8s", TEMPO_WORKER_APP, channel="dev/edge", trust=True)
    juju.integrate(f"{TEMPO_APP}:s3", SEAWEED_APP)
    juju.integrate(f"{TEMPO_APP}:tempo-cluster", f"{TEMPO_WORKER_APP}:tempo-cluster")
    return {TEMPO_APP, TEMPO_WORKER_APP, SEAWEED_APP}


@retry(
    wait=wait_exponential(multiplier=2, min=2, max=30), stop=stop_after_delay(300), reraise=True
)
def assert_traces_in_tempo(tempo_ip: str, *, service_name: str) -> None:
    """Assert that Tempo contains at least one trace from the given service.

    Retried with exponential back-off for up to 5 minutes to account for span
    flush and ingestion lag.
    """
    url = f"http://{tempo_ip}:{TEMPO_QUERY_PORT}/api/search?tags=service.name%3D{service_name}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    traces = data.get("traces", [])
    assert traces, (
        f"No traces from '{service_name}' found in Tempo at {tempo_ip}:{TEMPO_QUERY_PORT}."
    )

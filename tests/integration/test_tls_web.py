#!/usr/bin/env python3
# Copyright 2023 Ubuntu
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager TLS web endpoint."""

import logging
import tempfile
from pathlib import Path

import jubilant
import pytest
from helpers import ALERTMANAGER_IMAGE, curl, get_unit_address

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"
CA_APP = "ca"


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path):
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        trust=True,
    )
    juju.deploy("self-signed-certificates", CA_APP, channel="edge")
    juju.integrate(f"{AM_APP}:certificates", CA_APP)
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP, CA_APP)
        and jubilant.all_agents_idle(s, AM_APP, CA_APP),
        timeout=600,
    )


def test_tls_files_exist(juju):
    config_path = "/etc/alertmanager/"
    stdout = juju.cli(
        "exec", "--unit", f"{AM_APP}/0", "--container", "alertmanager", "--", "ls", config_path
    )
    logger.info("Contents of %s: %s", config_path, stdout)


def test_server_cert_san(juju):
    am_ip = get_unit_address(juju, AM_APP, 0)
    result = juju.cli(
        "exec",
        "--unit", f"{AM_APP}/0",
        "--container", "alertmanager",
        "--",
        "sh", "-c",
        f"echo | openssl s_client -showcerts -servername {am_ip}:9093 -connect {am_ip}:9093 2>/dev/null"
        " | openssl x509 -inform pem -noout -text",
    )
    fqdn = f"{AM_APP}-0.{AM_APP}-endpoints.{juju.model}.svc.cluster.local"
    assert fqdn in result, f"Expected SAN {fqdn!r} not found in cert output"


def _assert_https_reachable(juju) -> None:
    task = juju.run(f"{CA_APP}/0", "get-ca-certificate")
    cert = task.results["ca-certificate"]
    am_ip = get_unit_address(juju, AM_APP, 0)
    fqdn = f"{AM_APP}-0.{AM_APP}-endpoints.{juju.model}.svc.cluster.local"
    with tempfile.TemporaryDirectory() as cert_dir:
        cert_path = Path(cert_dir) / "local.cert"
        cert_path.write_text(cert)
        response = curl(
            cert_dir=Path(cert_dir),
            cert_path=cert_path,
            ip_addr=am_ip,
            mock_url=f"https://{fqdn}:9093/-/ready",
        )
    assert "OK" in response, f"HTTPS endpoint not reachable; response: {response}"


def test_https_reachable(juju):
    _assert_https_reachable(juju)


def test_https_still_reachable_after_refresh(juju, charm_path: Path):
    juju.refresh(AM_APP, path=str(charm_path))
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP, CA_APP)
        and jubilant.all_agents_idle(s, AM_APP, CA_APP),
        timeout=600,
    )
    _assert_https_reachable(juju)

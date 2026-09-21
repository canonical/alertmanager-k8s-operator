#!/usr/bin/env python3
# Copyright 2023 Ubuntu
# See LICENSE file for licensing details.

"""Integration tests: Alertmanager TLS web endpoint."""

import logging
import tempfile
from pathlib import Path

import jubilant
import lightkube
import pytest
import yaml
from helpers import (
    ALERTMANAGER_IMAGE,
    assert_security_context,
    curl,
    generate_container_securitycontext_map,
    get_pod_names,
    get_unit_address,
)

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"
CA_APP = "ca"
METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(
    METADATA,
    juju_user_id=171 if METADATA.get("charm-user") == "sudoer" else 170,
)


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
        delay=30,
        successes=3,
    )


def test_tls_files_exist(juju):
    config_path = "/etc/alertmanager/"
    stdout = juju.ssh(f"{AM_APP}/0", f"ls {config_path}", container="alertmanager")
    logger.info("Contents of %s: %s", config_path, stdout)


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP))
def test_container_security_context(juju, container_name: str):
    lightkube_client = lightkube.Client()
    pod_name = get_pod_names(lightkube_client, juju.model, AM_APP)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        juju.model,
    )


def test_charm_ca_certificate_installed(juju):
    output = juju.ssh(
        f"{AM_APP}/0",
        "id -u && test -f /usr/local/share/ca-certificates/cos-ca.crt",
        container="charm",
    )
    assert output.strip().splitlines()[0] == "171"


def test_server_cert_san(juju):
    am_ip = get_unit_address(juju, AM_APP, 0)
    # Run from the charm container (ubuntu-based, has openssl); connects to the alertmanager
    # pod IP which is reachable within the cluster from the same pod.
    result = juju.ssh(
        f"{AM_APP}/0",
        f"echo | openssl s_client -showcerts -servername {am_ip}:9093 -connect {am_ip}:9093 2>/dev/null"
        " | openssl x509 -inform pem -noout -text",
        container="charm",
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
        delay=30,
        successes=3,
    )
    _assert_https_reachable(juju)

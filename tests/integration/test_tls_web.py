#!/usr/bin/env python3
# Copyright 2023 Ubuntu
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import sh
import yaml
from helpers import curl, get_unit_address
from pytest_operator.plugin import OpsTest

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
alertmanager_image_rev = METADATA["resources"]["alertmanager-image"]["upstream-source"]
am = SimpleNamespace(name="alertmanager", scale=1)
ca = SimpleNamespace(name="ca")

# FIXME change scale to 2 once the tls_certificate lib issue is fixed
# https://github.com/canonical/tls-certificates-interface/issues/57


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Deploy 2 alertmanager units, related to a local CA."""
    assert ops_test.model
    # Deploy the charm and wait for active/idle status
    sh.juju.deploy(
        charm_under_test,
        "alertmanager",
        f"--num-units={am.scale}",
        model=ops_test.model.name,
        resource=f"alertmanager-image={alertmanager_image_rev}",
        trust=True,
    )
    sh.juju.deploy("self-signed-certificates", "ca", model=ops_test.model.name, channel="edge")
    sh.juju.relate("alertmanager:certificates", "ca", model=ops_test.model.name)

    await ops_test.model.wait_for_idle(
        apps=["alertmanager", "ca"],
        status="active",
        raise_on_error=False,
        timeout=600,
        idle_period=30,
    )


@pytest.mark.abort_on_fail
async def test_tls_files_created(ops_test: OpsTest):
    """Make sure charm code created web-config, cert and key files."""
    # juju ssh --container alertmanager am/0 ls /etc/alertmanager/
    config_path = "/etc/alertmanager/"
    for i in range(am.scale):
        unit_name = f"{am.name}/{i}"
        rc, stdout, stderr = await ops_test.juju(
            "ssh", "--container", "alertmanager", unit_name, "ls", f"{config_path}"
        )
        logger.info("%s: contents of %s: %s", unit_name, config_path, stdout or stderr)


@pytest.mark.abort_on_fail
async def test_server_cert(ops_test: OpsTest):
    """Inspect server cert and confirm `X509v3 Subject Alternative Name` field is as expected."""
    # echo \
    #   | openssl s_client -showcerts -servername $IPADDR:9093 -connect $IPADDR:9093 2>/dev/null \
    #   | openssl x509 -inform pem -noout -text
    am_ip_addrs = [await get_unit_address(ops_test, am.name, i) for i in range(am.scale)]
    for am_ip in am_ip_addrs:
        cmd = [
            "sh",
            "-c",
            f"echo | openssl s_client -showcerts -servername {am_ip}:9093 -connect {am_ip}:9093 2>/dev/null | openssl x509 -inform pem -noout -text",
        ]
        retcode, stdout, stderr = await ops_test.run(*cmd)
        fqdn = f"{am.name}-0.{am.name}-endpoints.{ops_test.model_name}.svc.cluster.local"
        assert fqdn in stdout


@pytest.mark.abort_on_fail
async def test_https_reachable(ops_test: OpsTest, temp_dir):
    """Make sure alertmanager's https endpoint is reachable using curl and ca cert."""
    for i in range(am.scale):
        # Save CA cert locally
        # juju show-unit am/0 --format yaml | yq '.am/0."relation-info"[0]."local-unit".data.ca' > /tmp/cacert.pem
        # juju run ca/0 get-ca-certificate --format json | jq -r '."ca/0".results."ca-certificate"' > internal.cert
        cmd = [
            "sh",
            "-c",
            f'juju run {ca.name}/0 get-ca-certificate --format json | jq -r \'."{ca.name}/0".results."ca-certificate"\'',
        ]
        logger.info("Obtaining CA cert with command: %s", " ".join(cmd))
        retcode, stdout, stderr = await ops_test.run(*cmd)
        cert = stdout
        cert_path = temp_dir / "local.cert"
        with open(cert_path, "wt") as f:
            f.writelines(cert)

        # Confirm alertmanager TLS endpoint reachable
        # curl --fail-with-body --capath /tmp --cacert /tmp/cacert.pem https://alertmanager.local:9093/-/ready
        ip_addr = await get_unit_address(ops_test, am.name, i)
        fqdn = f"{am.name}-0.{am.name}-endpoints.{ops_test.model_name}.svc.cluster.local"
        response = await curl(
            ops_test,
            cert_dir=temp_dir,
            cert_path=cert_path,
            ip_addr=ip_addr,
            mock_url=f"https://{fqdn}:9093/-/ready",
        )
        assert "OK" in response


@pytest.mark.abort_on_fail
async def test_https_still_reachable_after_refresh(ops_test: OpsTest, charm_under_test, temp_dir):
    """Make sure alertmanager's https endpoint is still reachable after an upgrade."""
    assert ops_test.model
    sh.juju.refresh("alertmanager", model=ops_test.model.name, path=charm_under_test)
    await ops_test.model.wait_for_idle(
        apps=["alertmanager", "ca"],
        status="active",
        raise_on_error=False,
        timeout=600,
        idle_period=30,
    )
    await test_https_reachable(ops_test, temp_dir)

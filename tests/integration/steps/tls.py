# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about alertmanager serving over TLS."""

import tempfile
from pathlib import Path

import jubilant
from helpers import AM_APP, curl, get_unit_address, unit_fqdn
from pytest_bdd import given, parsers, then

from steps.deployment import deploy_alertmanager
from steps.relations import COUNTERPARTS, relate_to

# An alertmanager serving over HTTPS is an application of its own, next to the plain
# one. Removing the CA relation would turn TLS off again, but it would restart the
# workload, and each scenario would then depend on what the previous one left behind.
TLS_APP = "alertmanager-tls"


@given(parsers.parse("alertmanager serves over {scheme}"), target_fixture="app")
def serves_over(juju: jubilant.Juju, charm_path: Path, scheme: str) -> str:
    app = TLS_APP if scheme == "HTTPS" else AM_APP
    deploy_alertmanager(juju, charm_path, app)
    if scheme == "HTTPS":
        relate_to(juju, app, "a CA", "certificates")
    return app


@then("the certificate alertmanager serves names the unit's in-cluster FQDN")
def certificate_names_fqdn(juju: jubilant.Juju, app: str):
    address = get_unit_address(juju, app, 0)
    # The charm container is ubuntu-based and has openssl; it shares the pod's network.
    certificate = juju.ssh(
        f"{app}/0",
        f"echo | openssl s_client -showcerts -servername {address}:9093"
        f" -connect {address}:9093 2>/dev/null | openssl x509 -inform pem -noout -text",
        container="charm",
    )
    assert unit_fqdn(juju, app, 0) in certificate


@then("alertmanager answers over HTTPS, verified against the CA")
def answers_over_https(juju: jubilant.Juju, app: str):
    ca_app = COUNTERPARTS["a CA"].app
    ca_certificate = juju.run(f"{ca_app}/0", "get-ca-certificate").results["ca-certificate"]
    with tempfile.TemporaryDirectory() as cert_dir:
        cert_path = Path(cert_dir) / "local.cert"
        cert_path.write_text(ca_certificate)
        response = curl(
            cert_dir=Path(cert_dir),
            cert_path=cert_path,
            ip_addr=get_unit_address(juju, app, 0),
            mock_url=f"https://{unit_fqdn(juju, app, 0)}:9093/-/ready",
        )
    assert "OK" in response

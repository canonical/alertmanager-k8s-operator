# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the workload trust store is rebuilt from up-to-date CA files.

`update-ca-certificates` builds the workload's trust store (/etc/ssl/certs/ca-certificates.crt)
from the CA files that are on disk at the moment it runs. Pebble verifies the TLS endpoints it
forwards logs to against that store, so every CA file the charm manages must be written (or
removed) before the store is rebuilt, not later in the same hook.
"""

import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

import ops
import pytest
from charms.tls_certificates_interface.v4.tls_certificates import (
    LIBID,
    Certificate,
    CertificateRequestAttributes,
    PrivateKey,
)
from ops.testing import Container, Context, Mount, Relation, Secret, State

STALE_CA = "-----BEGIN CERTIFICATE-----\n ... stale CA ... \n-----END CERTIFICATE-----"
RECEIVED_CA = "-----BEGIN CERTIFICATE-----\n ... received CA ... \n-----END CERTIFICATE-----"


@pytest.fixture(autouse=True)
def local_ca_dir(tmp_path):
    """Stand-in for /usr/local/share/ca-certificates, the folder of CAs to trust.

    `_update_ca_certs` also writes the CAs to the charm container's real filesystem, so point
    the charm at a temp dir instead, as in test_receive_ca_cert.py. The workload container
    then uses the same paths.
    """
    path = tmp_path / "ca-certificates"
    with patch.multiple(
        "src.charm.AlertmanagerCharm",
        _ca_cert_path=str(path / "cos-ca.crt"),
        _recv_ca_cert_folder_path=str(path / "juju_receive-ca-cert"),
    ):
        yield str(path)


@pytest.fixture
def workload_ca_dir(tmp_path) -> Path:
    """The folder that holds the CA files of the workload container.

    `ops.testing` wipes the workload filesystem before each run, so the workload's CA folder is
    mounted from here: a test can leave CA files in it, as an earlier hook would have, and read
    them while the charm runs.
    """
    path = tmp_path / "workload-ca-certificates"
    path.mkdir()
    return path


@pytest.fixture
def container(container: Container, local_ca_dir, workload_ca_dir) -> Container:
    """The alertmanager container, with its CA folder mounted from `workload_ca_dir`."""
    return dataclasses.replace(
        container,
        mounts={"ca-certificates": Mount(location=local_ca_dir, source=workload_ca_dir)},
    )


@pytest.fixture
def trust_store_rebuilds(workload_ca_dir):
    """The workload's CA files, as they were each time the charm rebuilt the trust store.

    An `ops.testing.Exec` can't run code, and `Context.exec_history` doesn't record what was on
    disk at the time. So wrap `Container.exec`, and read the workload's CA files just before
    `update-ca-certificates` runs there.
    """
    rebuilds: List[Dict[str, str]] = []
    real_exec = ops.Container.exec

    def exec_after_reading_cas(container: ops.Container, command, **kwargs):
        if container.name == "alertmanager" and command[0] == "update-ca-certificates":
            rebuilds.append(
                {
                    str(path.relative_to(workload_ca_dir)): path.read_text()
                    for path in workload_ca_dir.rglob("*.crt")
                }
            )
        return real_exec(container, command, **kwargs)

    with patch.object(ops.Container, "exec", exec_after_reading_cas):
        yield rebuilds


@pytest.fixture(scope="module")
def ca():
    """A CA, as its private key and its self-signed certificate."""
    key = PrivateKey.generate()
    certificate = Certificate.generate_self_signed_ca(
        CertificateRequestAttributes(common_name="ca", is_ca=True), key, timedelta(days=1)
    )
    return key, certificate


@pytest.fixture
def certificates_relation(ca, fqdn):
    """A `certificates` relation where the CA has issued the certificate the unit asked for.

    Returns the relation, and the secret in which the tls_certificates library keeps the
    unit's private key.
    """
    ca_key, ca_certificate = ca
    key = PrivateKey.generate()
    # The same attributes as the charm's own request, so that the library accepts the certificate
    csr = CertificateRequestAttributes(
        common_name="alertmanager-k8s", sans_dns=frozenset((fqdn,))
    ).generate_csr(key)
    certificate = Certificate.generate(
        csr=csr, ca=ca_certificate, ca_private_key=ca_key, validity=timedelta(days=1)
    )
    relation = Relation(
        "certificates",
        remote_app_name="ca",
        local_unit_data={
            "certificate_signing_requests": json.dumps(
                [{"certificate_signing_request": str(csr), "ca": False}]
            )
        },
        remote_app_data={
            "certificates": json.dumps(
                [
                    {
                        "ca": str(ca_certificate),
                        "certificate_signing_request": str(csr),
                        "certificate": str(certificate),
                        "chain": [str(certificate), str(ca_certificate)],
                    }
                ]
            )
        },
    )
    private_key = Secret(
        {"private-key": str(key)}, label=f"{LIBID}-private-key-0-certificates", owner="unit"
    )
    return relation, private_key


@pytest.mark.parametrize(
    "ca_left_in_the_workload", [None, STALE_CA], ids=["first-ca", "replaced-ca"]
)
def test_the_ca_is_in_the_workload_before_the_trust_store_is_rebuilt(
    context: Context,
    base_state: State,
    ca,
    certificates_relation,
    workload_ca_dir,
    trust_store_rebuilds,
    ca_left_in_the_workload: Optional[str],
):
    # GIVEN a CA that has issued the charm a certificate over "certificates"
    relation, private_key = certificates_relation
    state_in = dataclasses.replace(
        base_state, relations=[*base_state.relations, relation], secrets=[private_key]
    )

    # AND, in the "replaced-ca" case, a workload that still holds a stale CA
    if ca_left_in_the_workload:
        (workload_ca_dir / "cos-ca.crt").write_text(ca_left_in_the_workload)

    # WHEN the charm gets the certificate
    context.run(context.on.relation_changed(relation), state_in)

    # THEN the CA was already in the workload when the trust store was last rebuilt
    _, ca_certificate = ca
    assert trust_store_rebuilds, "the workload trust store was never rebuilt"
    assert "cos-ca.crt" in trust_store_rebuilds[-1]
    assert trust_store_rebuilds[-1]["cos-ca.crt"] == str(ca_certificate)


def test_the_ca_is_gone_from_the_workload_before_the_trust_store_is_rebuilt(
    context: Context, base_state: State, workload_ca_dir, trust_store_rebuilds
):
    # GIVEN a workload that still holds the CA of a certificate the charm no longer has,
    # because the "certificates" relation was removed
    (workload_ca_dir / "cos-ca.crt").write_text(STALE_CA)

    # WHEN the charm next rebuilds the trust store
    context.run(context.on.config_changed(), base_state)

    # THEN the CA was already gone from the workload at that moment
    assert trust_store_rebuilds, "the workload trust store was never rebuilt"
    assert "cos-ca.crt" not in trust_store_rebuilds[-1]


def test_received_cas_are_in_the_workload_before_the_trust_store_is_rebuilt(
    context: Context, base_state: State, trust_store_rebuilds
):
    # GIVEN a CA received over "receive-ca-cert"
    relation = Relation(
        "receive-ca-cert", remote_app_data={"certificates": json.dumps([RECEIVED_CA])}
    )
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the relation changes
    context.run(context.on.relation_changed(relation), state_in)

    # THEN that CA was already in the workload when the trust store was last rebuilt
    assert trust_store_rebuilds, "the workload trust store was never rebuilt"
    assert RECEIVED_CA in trust_store_rebuilds[-1].values()

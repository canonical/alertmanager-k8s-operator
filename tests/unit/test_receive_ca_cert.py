# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the charm trusts CAs received over the `receive-ca-cert` relation."""

import dataclasses
import json
from unittest.mock import patch

import pytest
from ops.testing import Relation, State

CERT_A = "-----BEGIN CERTIFICATE-----\n ... cert A ... \n-----END CERTIFICATE-----"
CERT_B = "-----BEGIN CERTIFICATE-----\n ... cert B ... \n-----END CERTIFICATE-----"


@pytest.fixture
def recv_ca_cert_folder(alertmanager_charm):
    return alertmanager_charm._recv_ca_cert_folder_path.lstrip("/")


@pytest.fixture(autouse=True)
def redirect_charm_container_ca_dir(tmp_path):
    """`_update_ca_certs` also writes the received CAs to a real path on the charm.

    That's on the charm container's own filesystem (so the charm process's own HTTPS calls trust them),
    independently of the workload container paths that `ops.testing` mocks. Redirect
    that real path to a throwaway temp dir so tests don't need (and don't get) root
    access to `/usr/local/share/ca-certificates/`.
    """
    with patch(
        "src.charm.AlertmanagerCharm._recv_ca_cert_folder_path",
        str(tmp_path / "juju_receive-ca-cert"),
    ):
        yield


def test_no_receive_ca_cert_relation_writes_nothing(
    context, base_state: State, recv_ca_cert_folder
):
    # GIVEN the charm has no `receive-ca-cert` relation
    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), base_state)

    # THEN no CA certs are written to the workload
    container = state.get_container("alertmanager")
    fs = container.get_filesystem(context)
    assert not fs.joinpath(recv_ca_cert_folder).exists()


def test_ca_cert_is_written_to_the_workload_on_relation_changed(
    context, base_state: State, recv_ca_cert_folder
):
    # GIVEN the charm is related over `receive-ca-cert` to a CA provider
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([CERT_A])})
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the relation-changed hook fires
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN the CA cert is written to the workload container
    container = state.get_container("alertmanager")
    fs = container.get_filesystem(context)
    certs_dir = fs.joinpath(recv_ca_cert_folder)
    assert certs_dir.exists()
    assert {f.read_text() for f in certs_dir.glob("*.crt")} == {CERT_A}


def test_ca_trust_survives_a_workload_container_restart(
    context, base_state: State, recv_ca_cert_folder
):
    """Regression test for the `_on_pebble_ready` CA-refresh gap.

    A workload-container restart (e.g. an OOM kill, or k8s rescheduling the
    container) recreates the container's filesystem from scratch, wiping out any
    previously-written `receive-ca-cert` trust bundle, while
    no relation-changed/-broken event fires).
    """
    # GIVEN a `receive-ca-cert` relation whose CA was already trusted...
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([CERT_A])})
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # ...but the workload container's filesystem is fresh (no CA files on disk),
    # simulating a restarted container whose relation data hasn't changed.
    container = state_in.get_container("alertmanager")
    assert not container.get_filesystem(context).joinpath(recv_ca_cert_folder).exists()

    # WHEN only `pebble-ready` fires (no relation event)
    state = context.run(context.on.pebble_ready(container), state_in)

    # THEN the CA trust bundle is (re)written anyway
    fs = state.get_container("alertmanager").get_filesystem(context)
    certs_dir = fs.joinpath(recv_ca_cert_folder)
    assert certs_dir.exists()
    assert {f.read_text() for f in certs_dir.glob("*.crt")} == {CERT_A}


def test_ca_cert_is_removed_on_relation_broken(context, base_state: State, recv_ca_cert_folder):
    # GIVEN a CA trusted over `receive-ca-cert`
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([CERT_A])})
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])
    state = context.run(context.on.relation_changed(relation), state_in)

    # WHEN the relation is removed
    state = context.run(context.on.relation_broken(relation), state)

    # THEN its CA cert is removed from the workload
    fs = state.get_container("alertmanager").get_filesystem(context)
    certs_dir = fs.joinpath(recv_ca_cert_folder)
    assert not certs_dir.exists() or not list(certs_dir.glob("*.crt"))


def test_multiple_cas_are_all_trusted(context, base_state: State, recv_ca_cert_folder):
    # GIVEN two `receive-ca-cert` relations providing different CAs
    relation_a = Relation(
        "receive-ca-cert", remote_app_data={"certificates": json.dumps([CERT_A])}
    )
    relation_b = Relation(
        "receive-ca-cert", remote_app_data={"certificates": json.dumps([CERT_B])}
    )
    state_in = dataclasses.replace(
        base_state, relations=[*base_state.relations, relation_a, relation_b]
    )

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation_a), state_in)

    # THEN both CAs are trusted
    fs = state.get_container("alertmanager").get_filesystem(context)
    certs_dir = fs.joinpath(recv_ca_cert_folder)
    assert {f.read_text() for f in certs_dir.glob("*.crt")} == {CERT_A, CERT_B}

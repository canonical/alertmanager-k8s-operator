#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the external URL alertmanager advertises follows its ingress.

Without ingress the charm uses its own fqdn; with ingress it uses the URL traefik gives it.
"""

import dataclasses
import json

import pytest
from helpers import cli_arg, cluster_peers
from ops.testing import Context, Relation, State

EXTERNAL_URL = "http://foo.bar.ingress/path/to/mdl-alertmanager-k8s"


def external_url(state: State):
    return cli_arg(state, "--web.external-url")


def ingress(url: str = "") -> Relation:
    """An ingress relation; without a url, traefik has not published one yet."""
    return Relation(
        "ingress",
        id=99,
        remote_app_name="traefik-app",
        remote_app_data={"ingress": json.dumps({"url": url})} if url else {},
    )


def test_external_url_is_the_fqdn_without_ingress(context: Context, base_state: State, fqdn, port):
    # GIVEN a charm with no ingress relation
    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), base_state)

    # THEN it advertises its own fqdn
    assert external_url(state) == f"http://{fqdn}:{port}"


def test_external_url_is_the_fqdn_while_ingress_is_not_ready(
    context: Context, base_state: State, fqdn, port
):
    # GIVEN an ingress relation for which traefik has not published a url yet
    relation = ingress()
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN it still advertises its own fqdn
    assert external_url(state) == f"http://{fqdn}:{port}"


def test_ingress_url_overrides_the_fqdn(context: Context, base_state: State):
    # GIVEN an ingress relation for which traefik has published a url
    relation = ingress(EXTERNAL_URL)
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN it advertises the ingress url instead of its fqdn
    assert external_url(state) == EXTERNAL_URL


def test_external_url_falls_back_to_the_fqdn_when_ingress_is_revoked(
    context: Context, base_state: State, fqdn, port
):
    # GIVEN a charm advertising an ingress url
    relation = ingress(EXTERNAL_URL)
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])
    state = context.run(context.on.relation_changed(relation), state_in)
    assert external_url(state) == EXTERNAL_URL

    # WHEN the ingress relation is removed
    state = context.run(context.on.relation_broken(state.get_relation(relation.id)), state)
    state = dataclasses.replace(
        state, relations=[r for r in state.relations if r.id != relation.id]
    )
    state = context.run(context.on.update_status(), state)

    # THEN it advertises its own fqdn again
    assert external_url(state) == f"http://{fqdn}:{port}"


@pytest.mark.parametrize("fqdn", ["fqdn-0"])
def test_peer_units_are_passed_to_alertmanager_as_cluster_peers(
    context: Context, base_state: State, peer_relation, port
):
    # GIVEN a three-unit cluster whose peers have published their addresses
    peers = dataclasses.replace(
        peer_relation,
        peers_data={unit: {"private_address": f"http://fqdn-{unit}:{port}"} for unit in (1, 2)},
    )
    state_in = dataclasses.replace(base_state, relations=[peers])

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(peers, remote_unit=2), state_in)

    # THEN each peer is passed as a cluster peer on the HA port, not the API port
    assert cluster_peers(state) == ["fqdn-1:9094", "fqdn-2:9094"]

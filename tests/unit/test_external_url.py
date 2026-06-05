#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for external URL handling."""

import dataclasses
import json
from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from ops.testing import Context, Relation, State


@pytest.mark.skip("https://github.com/canonical/operator/issues/736")
class TestExternalUrl:
    """Tests for external URL configuration via ingress."""

    @pytest.fixture
    def initial_state(self, context: Context) -> State:
        """Set up charm with alerting relation."""
        with patch("socket.getfqdn", new=lambda *args: "fqdn"):
            state = begin_with_initial_hooks_isolated(context, leader=True)

            # Add alerting relation
            alerting_rel = Relation("alerting")
            state = add_relation_sequence(context, state, alerting_rel)
            yield state

    def test_traefik_overrides_fqdn(self, context: Context, initial_state: State):
        """The ingress URL must override the fqdn-based external url."""
        with patch("socket.getfqdn", new=lambda *args: "fqdn"):
            # GIVEN a charm with the fqdn as its external URL
            container = initial_state.get_container("alertmanager")
            command = container.layers["alertmanager"].services["alertmanager"].command
            assert "--web.external-url=http://fqdn:9093" in command

            # WHEN a relation with traefik is formed and ingress becomes ready
            ingress_rel = Relation(
                "ingress",
                remote_app_data={
                    "ingress": json.dumps(
                        {"url": "http://foo.bar.ingress:80/path/to/mdl-alertmanager-k8s"}
                    )
                },
            )
            state = add_relation_sequence(context, initial_state, ingress_rel)

            # THEN the external url from the ingress relation overrides the fqdn
            container = state.get_container("alertmanager")
            command = container.layers["alertmanager"].services["alertmanager"].command
            assert (
                "--web.external-url=http://foo.bar.ingress:80/path/to/mdl-alertmanager-k8s"
                in command
            )

    def test_cluster_addresses(self, context: Context, initial_state: State):
        """Test cluster peer addresses are correctly configured."""
        with patch("socket.getfqdn", new=lambda *args: "fqdn-0"):
            # GIVEN an alertmanager charm with 3 units in total
            peer_rel = initial_state.get_relations("replicas")[0]
            peer_rel_with_units = dataclasses.replace(
                peer_rel,
                peers_data={
                    1: {"private_address": "http://fqdn-1:9093"},
                    2: {"private_address": "http://fqdn-2:9093"},
                },
            )
            state = dataclasses.replace(
                initial_state,
                relations=[
                    peer_rel_with_units if r.id == peer_rel.id else r
                    for r in initial_state.relations
                ],
            )
            state = context.run(context.on.relation_changed(peer_rel_with_units), state)

            # THEN the `--cluster.peer` args are made up of the hostname and HA port
            container = state.get_container("alertmanager")
            command = container.layers["alertmanager"].services["alertmanager"].command

            # Extract cluster.peer args
            cluster_args = sorted(
                arg.split("=")[1] for arg in command.split() if arg.startswith("--cluster.peer=")
            )
            assert cluster_args == ["fqdn-1:9094", "fqdn-2:9094"]

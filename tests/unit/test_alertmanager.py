#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from alertmanager import _parse_peer_addresses


class TestParsePeerAddresses:

    @pytest.mark.parametrize(
        "addresses, port, expected",
        [
            (
                ["http://peer1:1234", "https://peer2:1234"],
                5555,
                ["peer1:5555", "peer2:5555"],
            ),
            (
                ["httppppp://peer1:1234"],
                "6666",
                ["peer1:6666"],
            ),
            (
                [],
                "1234",
                []
            )
        ]
    )
    def test_parse_peer_addresses(self, addresses, port, expected):
        assert _parse_peer_addresses(addresses, port) == expected

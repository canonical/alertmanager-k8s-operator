#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charm_helpers import add_port_to_addresses, get_hostname_from_address


class TestHelpers:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("http://something.com:1234/path;param?query=arg#frag", "something.com"),
            ("https://something.com/path;param?query=arg#frag", "something.com"),
        ],
    )
    def test_get_hostname_from_address(self, url, expected):
        hostname = get_hostname_from_address(url)
        assert hostname == expected

    @pytest.mark.parametrize(
        "addresses, port, expected",
        [
            (
                ["something.com", "something-else.com"],
                "1234",
                ["something.com:1234", "something-else.com:1234"],
            ),
            (
                ["something.com", "something-else.com"],
                1234,
                ["something.com:1234", "something-else.com:1234"],
            ),
        ],
    )
    def test_add_port_to_addresses(self, addresses, port, expected):
        addresses_with_port = add_port_to_addresses(addresses, port)
        assert addresses_with_port == expected

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charm_helpers import get_hostname_from_address


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

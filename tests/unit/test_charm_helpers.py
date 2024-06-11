#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from charm_helpers import remove_scheme


class TestHelpers(unittest.TestCase):
    def test_remove_scheme(self):
        url_expected = "something.com/path;param?query=arg#frag"
        url_with_scheme = f"https://{url_expected}"

        url_with_scheme_removed = remove_scheme(url_with_scheme)
        self.assertEqual(url_expected, url_with_scheme_removed)

    def test_remove_scheme_when_scheme_doesnt_exist(self):
        url_expected = "something.com/path;param?query=arg#frag"

        url_with_scheme_removed = remove_scheme(url_expected)
        self.assertEqual(url_expected, url_with_scheme_removed)

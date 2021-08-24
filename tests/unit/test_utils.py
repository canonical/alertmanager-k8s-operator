#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import utils
import unittest
from unittest.mock import patch
from contextlib import contextmanager


class TestUtils(unittest.TestCase):
    def test_append_unless(self):
        # unless = None
        self.assertEqual("address:port", utils.append_unless(None, "address", ":port"))
        self.assertEqual(None, utils.append_unless(None, None, ":port"))

        # unless = string
        self.assertEqual("basesuffix", utils.append_unless("bad", "base", "suffix"))
        self.assertEqual("bad", utils.append_unless("bad", "bad", "suffix"))

        # unless = None, args = lists
        self.assertEqual([1, 2, 3], utils.append_unless(None, [1, 2], [3]))
        self.assertEqual(None, utils.append_unless(None, None, [3]))

    def test_sha256(self):
        self.assertEqual(
            "a7b88adc9b60fc386f1deb77909f0f415817db7281e708c57207d723b9412d94",
            utils.sha256("test string\nwith newline"),
        )

    def test_fetch_url(self):
        self.assertEqual(None, utils.fetch_url("no such thing"))
        self.assertEqual(None, utils.fetch_url("http://no-such-thing-hopefully.abc/asdasd123"))

        def urlopen_mock(html: bytes, code: int):
            class MockResponse:
                def read(self):
                    return html

                def getcode(self):
                    return code

            @contextmanager
            def urlopen(url):
                yield MockResponse()

            return urlopen

        with patch("urllib.request.urlopen", urlopen_mock(b"works", 200)):
            self.assertEqual(b"works", utils.fetch_url("http://canonical.com/"))

        # return `None` for any code >= 400
        with patch("urllib.request.urlopen", urlopen_mock(b"some message", 400)):
            self.assertEqual(None, utils.fetch_url("http://canonical.com/"))

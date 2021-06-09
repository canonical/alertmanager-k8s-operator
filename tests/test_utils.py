# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import utils
import unittest
from unittest.mock import patch
from contextlib import contextmanager


class TestUtils(unittest.TestCase):
    def test_append_unless(self):
        # unless = None
        self.assertEqual('address:port', utils.append_unless(None, 'address', ':port'))
        self.assertEqual(None, utils.append_unless(None, None, ':port'))

        # unless = string
        self.assertEqual('basesuffix', utils.append_unless('bad', 'base', 'suffix'))
        self.assertEqual('bad', utils.append_unless('bad', 'bad', 'suffix'))

        # unless = None, args = lists
        self.assertEqual([1, 2, 3], utils.append_unless(None, [1, 2], [3]))
        self.assertEqual(None, utils.append_unless(None, None, [3]))

    def test_md5(self):
        self.assertEqual('50e1eeff19b2501c791612cd907fff7a',
                         utils.md5('test string\nwith newline'))

    def test_fetch_url(self):
        self.assertEqual(None, utils.fetch_url('no such thing'))
        self.assertEqual(None, utils.fetch_url('http://no-such-thing-hopefully.abc/asdasd123'))

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

        with patch('urllib.request.urlopen', urlopen_mock(b"works", 200)):
            self.assertEqual(b"works", utils.fetch_url('http://canonical.com/'))

        # return `None` for any code >= 400
        with patch('urllib.request.urlopen', urlopen_mock(b"some message", 400)):
            self.assertEqual(None, utils.fetch_url('http://canonical.com/'))

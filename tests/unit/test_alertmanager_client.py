#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import patch

from alertmanager_client import Alertmanager


class TestAlertmanagerAPIClient(unittest.TestCase):
    def setUp(self):
        self.api = Alertmanager("address", 12345)

    def test_base_url(self):
        self.assertEqual("http://address:12345/", self.api.base_url)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_reload_succeed(self, urlopen_mock):
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        self.assertTrue(self.api.reload())
        urlopen_mock.assert_called()

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_status_succeed(self, urlopen_mock):
        urlopen_mock.return_value.read = lambda: json.dumps({"status": "fake"})
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        status = self.api.status()
        self.assertIsNotNone(status)
        self.assertDictEqual({"status": "fake"}, status)

    def test_reload_and_status_fail(self):
        def mock_connection_error(*args, **kwargs):
            import urllib.error

            raise urllib.error.HTTPError(
                url="url", code=500, msg="msg", hdrs={"hdr": "smth"}, fp=None
            )

        with patch("alertmanager_client.urllib.request.urlopen", mock_connection_error):
            self.assertFalse(self.api.reload())

        with patch("alertmanager_client.urllib.request.urlopen", mock_connection_error):
            self.assertIsNone(self.api.status())

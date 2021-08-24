#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import patch

from alertmanager_client import AlertmanagerAPIClient


class TestAlertmanagerAPIClient(unittest.TestCase):
    def setUp(self):
        self.api = AlertmanagerAPIClient("address", 12345)

    def test_base_url(self):
        self.assertEqual("http://address:12345/", self.api.base_url)

    def test_reload_and_status(self):
        from collections import namedtuple

        Response = namedtuple("Response", ["status_code", "reason", "text", "ok"])

        # test succeess
        def mock_response(*args, **kwargs):
            return Response(200, "OK", json.dumps({"status": "fake"}), True)

        with patch("requests.post", mock_response):
            self.assertTrue(self.api.reload())

        with patch("requests.get", mock_response):
            status = self.api.status()
            self.assertIsNotNone(status)
            self.assertDictEqual({"status": "fake"}, status)

        # test failure
        def mock_connection_error(*args, **kwargs):
            import requests

            raise requests.exceptions.ConnectionError

        with patch("requests.post", mock_connection_error):
            self.assertFalse(self.api.reload())

        with patch("requests.get", mock_connection_error):
            self.assertIsNone(self.api.status())

        def mock_timeout(*args, **kwargs):
            import requests

            raise requests.exceptions.ConnectTimeout

        with patch("requests.post", mock_timeout):
            self.assertFalse(self.api.reload())

        with patch("requests.get", mock_timeout):
            self.assertIsNone(self.api.status())

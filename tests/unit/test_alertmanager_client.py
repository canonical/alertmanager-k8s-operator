#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from alertmanager_client import Alertmanager, AlertmanagerBadResponse


class TestAlertmanagerAPIClient(unittest.TestCase):
    def setUp(self):
        self.path = "custom/path"
        self.api = Alertmanager("address", 12345, web_route_prefix=self.path)

    def test_base_url(self):
        self.assertEqual(f"http://address:12345/{self.path}/", self.api.base_url)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_reload_succeed(self, urlopen_mock):
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        self.api.reload()
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
                url="mock://url",
                code=500,
                msg="mock msg",
                hdrs={"mock hdr": "mock smth"},  # type: ignore[arg-type]
                fp=None,
            )

        with patch("alertmanager_client.urllib.request.urlopen", mock_connection_error):
            self.assertRaises(AlertmanagerBadResponse, self.api.reload)

        with patch("alertmanager_client.urllib.request.urlopen", mock_connection_error):
            self.assertRaises(AlertmanagerBadResponse, self.api.status)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_version(self, urlopen_mock):
        urlopen_mock.return_value.read = lambda: json.dumps({"versionInfo": {"version": "0.1.2"}})
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        self.assertEqual(self.api.version, "0.1.2")

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_alerts_can_be_set(self, urlopen_mock):
        msg = "HTTP 200 OK"
        urlopen_mock.return_value = msg
        alerts = [
            {
                "startsAt": datetime.now().isoformat("T"),
                "status": "firing",
                "annotations": {
                    "summary": "A fake alert",
                },
                "labels": {
                    "alertname": "fake alert",
                },
            }
        ]
        status = self.api.set_alerts(alerts)
        urlopen_mock.assert_called()
        self.assertEqual(status, msg)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_available_alerts_are_returned(self, urlopen_mock):
        fake_alerts = [
            {
                "labels": {"name": "fake-alert"},
                "startsAt": datetime.now().isoformat("T"),
            }
        ]
        urlopen_mock.return_value.read = lambda: json.dumps(fake_alerts)
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        alerts = self.api.get_alerts()
        self.assertListEqual(alerts, fake_alerts)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_silences_can_be_set(self, urlopen_mock):
        msg = "HTTP 200 OK"
        urlopen_mock.return_value = msg
        matchers = [
            {
                "name": "alertname",
                "value": "fake-alert",
                "isRegex": False,
            }
        ]
        silence_start = datetime.now(timezone.utc)
        silence_end = silence_start + timedelta(minutes=60)
        status = self.api.set_silences(
            matchers=matchers, start_time=silence_start, end_time=silence_end
        )
        urlopen_mock.assert_called()
        self.assertEqual(status, msg)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_available_silences_are_returned(self, urlopen_mock):
        fake_silences = [
            {
                "id": "fake-silencer",
                "status": {"state": "active"},
                "startsAt": datetime.now().isoformat("T"),
                "endsAt": (datetime.now() + timedelta(minutes=60)).isoformat("T"),
                "matchers": [
                    {
                        "name": "alertname",
                        "value": "fake-alert",
                        "isRegex": False,
                    }
                ],
            }
        ]
        urlopen_mock.return_value.read = lambda: json.dumps(fake_silences)
        urlopen_mock.return_value.code = 200
        urlopen_mock.return_value.reason = "OK"

        alerts = self.api.get_silences()
        self.assertListEqual(alerts, fake_silences)

    @patch("alertmanager_client.urllib.request.urlopen")
    def test_silences_can_be_deleted(self, urlopen_mock):
        msg = "HTTP 200 OK"
        urlopen_mock.return_value = msg

        status = self.api.delete_silence("fake-id")
        urlopen_mock.assert_called()
        self.assertEqual(status, msg)

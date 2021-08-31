#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Client library for Alertmanager API."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class AlertmanagerBadResponse(RuntimeError):
    """A catch-all exception type to indicate 'no reply', regardless the reason."""


class Alertmanager:
    """Alertmanager HTTP API client."""

    def __init__(self, address: str = "localhost", port: int = 9093, timeout=2.0):
        self.base_url = f"http://{address}:{port}/"
        self.timeout = timeout

    def reload(self) -> bool:
        """Send a POST request to to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = urllib.parse.urljoin(self.base_url, "/-/reload")
        return bool(self._get(url, timeout=self.timeout))

    @staticmethod
    def _get(url: str, timeout: float) -> str:
        """Send a GET request with a timeout.

        Args:
            url: target url to GET from
            timeout: duration in seconds after which to return, regardless the result

        Raises:
            AlertmanagerBadResponse: If no response or invalid response, regardless the reason.
        """
        try:
            response = urllib.request.urlopen(url, data=None, timeout=timeout)
            if response.code == 200 and response.reason == "OK":
                return response.read()
            raise AlertmanagerBadResponse(
                f"Bad response (code={response.code}, reason={response.reason})"
            )
        except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
            raise AlertmanagerBadResponse("Bad response") from e

    def status(self) -> dict:
        """Obtain status information from the alertmanager server."""
        url = urllib.parse.urljoin(self.base_url, "/api/v2/status")
        try:
            return json.loads(self._get(url, timeout=self.timeout))
        except (TypeError, json.decoder.JSONDecodeError) as e:
            raise AlertmanagerBadResponse("Response is not a JSON string") from e

    @property
    def version(self) -> str:
        """Obtain version number from the alertmanager server."""
        try:
            return self.status()["versionInfo"]["version"]
        except KeyError as e:
            raise AlertmanagerBadResponse("Unexpected response") from e

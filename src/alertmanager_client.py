#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Client library for Alertmanager API."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

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
        for retry in reversed(range(3)):
            try:
                if resp := self._post(url, timeout=self.timeout):
                    logger.warning("reload: POST returned a non-empty response: %s", resp)
                    return False
                return True
            except AlertmanagerBadResponse as e:
                if retry == 0:
                    raise AlertmanagerBadResponse("Retry failed") from e
                else:
                    time.sleep(0.2)
                    continue

        assert False, "unreachable"  # help mypy (https://github.com/python/mypy/issues/8964)

    @staticmethod
    def _post(url: str, timeout: float, data=b"") -> bytes:
        """Send a POST request.

        For an empty POST request, the `data` arg must be b"" to tell urlopen it's a POST and not a
        GET.
        """
        return Alertmanager._open(url, data, timeout)

    @staticmethod
    def _get(url: str, timeout: float, data=None) -> bytes:
        """Send a GET request.

        The `data` arg must be None to tell urlopen it's a GET.
        """
        return Alertmanager._open(url, data, timeout)

    @staticmethod
    def _open(url: str, data: Optional[bytes], timeout: float) -> bytes:
        """Send a request using urlopen.

        Args:
            url: target url for the request
            data: bytes to send to target
            timeout: duration in seconds after which to return, regardless the result

        Raises:
            AlertmanagerBadResponse: If no response or invalid response, regardless the reason.
        """
        try:
            response = urllib.request.urlopen(url, data, timeout)
            if response.code == 200 and response.reason == "OK":
                return response.read()
            raise AlertmanagerBadResponse(
                f"Bad response (code={response.code}, reason={response.reason})"
            )
        except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
            raise AlertmanagerBadResponse("Bad response") from e

    def status(self) -> dict:
        """Obtain status information from the alertmanager server.

        Typical output:
        {
          "cluster": {
            "peers": [],
            "status": "disabled"
          },
          "config": {
            "original": "global: [...]"
          },
          "uptime": "2021-08-31T14:15:31.613Z",
          "versionInfo": {
            "branch": "HEAD",
            "buildDate": "20210324-17:46:50",
            "buildUser": "root@lgw01-amd64-031",
            "goVersion": "go1.14.15",
            "revision": "4c6c03ebfe21009c546e4d1e9b92c371d67c021d",
            "version": "0.21.0"
          }
        }
        """
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

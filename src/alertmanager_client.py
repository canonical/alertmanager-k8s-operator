#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


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
    def _get(url: str, timeout) -> Optional[str]:
        """Send a GET request with a timeout"""
        try:
            response = urllib.request.urlopen(url, data=None, timeout=timeout)
            if response.code == 200 and response.reason == "OK":
                text = response.read()
            else:
                text = None
        except (ValueError, urllib.error.HTTPError, urllib.error.URLError):
            text = None
        return text

    def status(self) -> Optional[dict]:
        """Obtain status information from the alertmanager server."""
        url = urllib.parse.urljoin(self.base_url, "/api/v2/status")
        return json.loads(response) if (response := self._get(url, timeout=self.timeout)) else None

    @property
    def version(self) -> str:
        """Obtain version number from the alertmanager server."""
        if status := self.status():
            return status["versionInfo"]["version"]
        return "0.0.0"

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import urllib
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class AlertmanagerAPIClient:
    """Alertmanager HTTP API client."""

    def __init__(self, address: str, port: int, timeout=2.0):
        self.base_url = f"http://{address}:{port}/"
        self.timeout = timeout

    def reload(self) -> bool:
        """Send a POST request to to hot-reload the config.
        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = urllib.parse.urljoin(self.base_url, "/-/reload")
        try:
            response = requests.post(url, timeout=self.timeout)
            logger.debug("config reload via %s: %d %s", url, response.status_code, response.reason)
            return response.status_code == 200 and response.reason == "OK"
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
            logger.debug("config reload error via %s: %s", url, str(e))
            return False

    @staticmethod
    def _get(url: str, timeout) -> Optional[dict]:
        """Send a GET request with a timeout"""
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                text = json.loads(response.text)
            else:
                text = None
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            text = None
        return text

    def status(self) -> Optional[dict]:
        """Obtain status information from the alertmanager server."""
        url = urllib.parse.urljoin(self.base_url, "/api/v2/status")
        return self._get(url, timeout=self.timeout)

    def silences(self, state: str = None) -> Optional[List[dict]]:
        """Obtain information on silences from the alertmanager server."""
        url = urllib.parse.urljoin(self.base_url, "/api/v2/silences")
        silences = self._get(url, timeout=self.timeout)

        # if GET failed or user did not provide a state to filter by, return as-is (possibly None);
        # else filter by state
        return (
            silences
            if silences is None or state is None
            else [s for s in silences if s.get("status") and s["status"].get("state") == state]
        )

    @property
    def version(self) -> Optional[str]:
        """Obtain version number from the alertmanager server."""
        if status := self.status():
            return status["versionInfo"]["version"]
        return

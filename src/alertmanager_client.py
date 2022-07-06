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

import yaml

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
        # for an empty POST request, the `data` arg must be b"" to tell urlopen it's a POST
        if resp := self._open(url, data=b"", timeout=self.timeout):
            logger.warning("reload: POST returned a non-empty response: %s", resp)
            return False
        return True

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
        for retry in reversed(range(3)):
            try:
                response = urllib.request.urlopen(url, data, timeout)
                if response.code == 200 and response.reason == "OK":
                    return response.read()
                elif retry == 0:
                    raise AlertmanagerBadResponse(
                        f"Bad response (code={response.code}, reason={response.reason})"
                    )

            except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
                if retry == 0:
                    raise AlertmanagerBadResponse("Bad response") from e

            time.sleep(0.2)

        assert False, "unreachable"  # help mypy (https://github.com/python/mypy/issues/8964)

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
            # the `data` arg must be None to tell urlopen it's a GET
            return json.loads(self._open(url, data=None, timeout=self.timeout))
        except (TypeError, json.decoder.JSONDecodeError) as e:
            raise AlertmanagerBadResponse("Response is not a JSON string") from e

    @property
    def version(self) -> str:
        """Obtain version number from the alertmanager server."""
        try:
            return self.status()["versionInfo"]["version"]
        except KeyError as e:
            raise AlertmanagerBadResponse("Unexpected response") from e

    def config(self) -> dict:
        """Obtain config from the alertmanager server.

        Typical output (here displayed in yaml format):
        global:
          resolve_timeout: 5m
          http_config:
            tls_config:
              insecure_skip_verify: true
          smtp_hello: localhost
          smtp_require_tls: true
          pagerduty_url: https://events.pagerduty.com/v2/enqueue
          opsgenie_api_url: https://api.opsgenie.com/
          wechat_api_url: https://qyapi.weixin.qq.com/cgi-bin/
          victorops_api_url: https://alert.victorops.com/integrations/generic/20131114/alert/
        route:
          receiver: dummy
          group_by:
            - juju_application
            - juju_model
            - juju_model_uuid
          group_wait: 30s
          group_interval: 5m
          repeat_interval: 1h
        receivers:
          - name: dummy
            webhook_configs:
              - send_resolved: true
                http_config:
                  tls_config:
                    insecure_skip_verify: true
                url: http://127.0.0.1:5001/
                max_alerts: 0
        templates: []
        """
        try:
            config = self.status()["config"]["original"]
        except KeyError as e:
            raise AlertmanagerBadResponse("Unexpected response") from e

        try:
            return yaml.safe_load(config)
        except yaml.YAMLError as e:
            raise AlertmanagerBadResponse("Response is not a YAML string") from e

    def _post(
        self, url: str, post_data: bytes, headers: dict = None, timeout: int = None
    ) -> bytes:
        """Make a HTTP POST request to Alertmanager.

        Args:
            url: string URL where POST request is sent.
            post_data: encoded string (bytes) of data to be posted.
            headers: dictionary containing HTTP headers to be used for POST request.
            timeout: numeric timeout value in seconds.

        Returns:
            urllib response object.
        """
        response = "".encode("utf-8")
        timeout = timeout or self.timeout
        request = urllib.request.Request(url, headers=headers or {}, data=post_data, method="POST")

        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            logger.debug(
                "Failed posting to %s, reason: %s",
                url,
                error.reason,
            )
        except urllib.error.URLError as error:
            logger.debug("Invalid URL %s : %s", url, error)
        except TimeoutError:
            logger.debug("Request timeout during posting to URL %s", url)
        return response

    def set_alerts(self, alerts: list) -> bytes:
        """Send a set of new alerts to alertmanger.

        Args:
            alerts: a list of alerts to be set. Format of this list is
               described here https://prometheus.io/docs/alerting/latest/clients/.

        Returns:
            urllib response object.
        """
        url = urllib.parse.urljoin(self.base_url, "/api/v1/alerts")
        headers = {"Content-Type": "application/json"}
        post_data = json.dumps(alerts).encode("utf-8")
        response = self._post(url, post_data, headers=headers)

        return response

#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests: custom alert template rendered in Slack receiver."""

import json
import logging
import time
from pathlib import Path

import jubilant
import pytest
import yaml
from helpers import ALERTMANAGER_IMAGE, is_alertmanager_up
from werkzeug.wrappers import Request, Response

logger = logging.getLogger(__name__)

AM_APP = "alertmanager"
RECEIVER_NAME = "fake-receiver"

callback_id = str(int(time.time()))
TEMPLATE = r'{{ define "slack.default.callbackid" }}' + callback_id + "{{ end }}"


@pytest.mark.juju_setup
def test_deploy(juju, charm_path: Path, httpserver):
    aconfig = {
        "global": {"http_config": {"tls_config": {"insecure_skip_verify": True}}},
        "route": {
            "group_by": ["alertname"],
            "group_wait": "3s",
            "group_interval": "5m",
            "repeat_interval": "1h",
            "receiver": RECEIVER_NAME,
        },
        "receivers": [
            {
                "name": RECEIVER_NAME,
                "slack_configs": [
                    {
                        "api_url": httpserver.url_for("/"),
                        "channel": "test",
                        "text": r"https://localhost/alerts/{{ .GroupLabels.alertname }}",
                    }
                ],
            }
        ],
    }
    juju.deploy(
        str(charm_path),
        AM_APP,
        resources={"alertmanager-image": ALERTMANAGER_IMAGE},
        config={"config_file": yaml.safe_dump(aconfig), "templates_file": TEMPLATE},
        trust=True,
    )
    juju.wait(
        lambda s: jubilant.all_active(s, AM_APP) and jubilant.all_agents_idle(s, AM_APP),
        timeout=1000,
        delay=30,
        successes=3,
    )
    assert is_alertmanager_up(juju, AM_APP)


def test_receiver_gets_alert_with_custom_callback_id(juju, httpserver):
    received: list = []

    def request_handler(request: Request):
        received.append(json.loads(request.data.decode("utf-8")))
        return Response("OK", status=200, content_type="text/plain")

    with httpserver.wait(timeout=120) as waiting:
        httpserver.expect_oneshot_request("/", method="POST").respond_with_handler(request_handler)
        juju.ssh(
            f"{AM_APP}/0",
            f"amtool alert add foo node=bar status=firing juju_model_uuid=1234"
            f" juju_application={AM_APP} juju_model=model_name --annotation=summary=summary",
            container="alertmanager",
        )

    assert waiting.result, "Alertmanager did not send an alert to the Slack receiver"
    assert received[0]["attachments"][0]["callback_id"] == callback_id, (
        f"Expected callback_id={callback_id}, got {received[0]['attachments'][0]['callback_id']}"
    )

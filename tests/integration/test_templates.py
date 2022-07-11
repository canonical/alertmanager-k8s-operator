#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from helpers import get_unit_address, is_alertmanager_up
from pytest_operator.plugin import OpsTest
from werkzeug.wrappers import Request, Response

from alertmanager_client import Alertmanager

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}
receiver_name = "fake-receiver"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    # deploy charm from local source folder
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name=app_name)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert ops_test.model.applications[app_name].units[0].workload_status == "active"
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_configure_alertmanager_with_templates(ops_test: OpsTest, httpserver):
    # define the alertmanager configuration
    aconfig = {
        "global": {"http_config": {"tls_config": {"insecure_skip_verify": True}}},
        "route": {
            "group_by": ["alertname"],
            "group_wait": "3s",
            "group_interval": "5m",
            "repeat_interval": "1h",
            "receiver": receiver_name,
        },
        "receivers": [
            {
                "name": receiver_name,
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

    # use a template to define the slack callback id
    atemplate = r'{{ define "slack.default.callbackid" }}2{{ end }}'
    # set alertmanager configuration and template file
    await ops_test.model.applications[app_name].set_config(
        {"config_file": yaml.safe_dump(aconfig), "templates_file": atemplate}
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=60)


@pytest.mark.abort_on_fail
async def test_receiver_gets_alert(ops_test: OpsTest, httpserver):
    # create an alert
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=5)
    alert_name = "fake-alert"
    model_uuid = "1234"
    alerts = [
        {
            "startsAt": start_time.isoformat("T"),
            "endsAt": end_time.isoformat("T"),
            "status": "firing",
            "annotations": {
                "summary": "A fake alert",
            },
            "labels": {
                "juju_model_uuid": model_uuid,
                "juju_application": app_name,
                "juju_model": ops_test.model_name,
                "alertname": alert_name,
            },
            "generatorURL": f"http://localhost/{alert_name}",
        }
    ]

    # define the expected slack notification for the alert
    # link = f"http://{app_name}-0:9093/#/alerts?receiver={receiver_name}"
    link = f"http://{app_name}-0.{app_name}-endpoints.{ops_test.model_name}.svc.cluster.local:9093/#/alerts?receiver={receiver_name}"
    expected_notification = {
        "channel": "test",
        "username": "Alertmanager",
        "attachments": [
            {
                "title": f"[FIRING:1] {alert_name} {app_name} {ops_test.model_name} {model_uuid} ",
                "title_link": link,
                "text": f"https://localhost/alerts/{alert_name}",
                "fallback": f"[FIRING:1] {alert_name} {app_name} {ops_test.model_name} {model_uuid}  | {link}",
                "callback_id": "2",
                "footer": "",
                "color": "danger",
                "mrkdwn_in": ["fallback", "pretext", "text"],
            }
        ],
    }

    request_from_alertmanager = None

    def request_handler(request: Request):
        """A request handler.

        Alertmanager's POST request looks like this:

        {'attachments': [{'callback_id': '2',
                  'color': 'danger',
                  'fallback': '[FIRING:1] fake-alert alertmanager-k8s '
                              'test-templates-klzm 1234  | '
                              'http://alertmanager-k8s-0.fqdn:9093/#/alerts?receiver=name',
                  'footer': '',
                  'mrkdwn_in': ['fallback', 'pretext', 'text'],
                  'text': 'https://localhost/alerts/fake-alert',
                  'title': '[FIRING:1] fake-alert alertmanager-k8s '
                           'test-templates-klzm 1234 ',
                  'title_link': 'http://alertmanager-k8s-0.fqdn:9093/#/alerts?receiver=name'}],
        'channel': 'test',
        'username': 'Alertmanager'}
        """
        nonlocal request_from_alertmanager
        response = Response("OK", status=200, content_type="text/plain")
        request_from_alertmanager = json.loads(request.data.decode("utf-8"))
        logger.info("Got Request Data : %s", request_from_alertmanager)
        return response

    # set the alert
    with httpserver.wait(timeout=120) as waiting:
        # expect an alert to be forwarded to the receiver
        httpserver.expect_oneshot_request("/", method="POST").respond_with_handler(request_handler)
        client_address = await get_unit_address(ops_test, app_name, 0)
        amanager = Alertmanager(address=client_address)
        amanager.set_alerts(alerts)

    # check receiver got an alert
    assert waiting.result
    assert request_from_alertmanager == expected_notification

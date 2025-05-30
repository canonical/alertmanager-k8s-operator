#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import time
from pathlib import Path

import pytest
import sh
import yaml
from helpers import is_alertmanager_up
from pytest_operator.plugin import OpsTest
from werkzeug.wrappers import Request, Response

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}
receiver_name = "fake-receiver"

# Define the template to use for testing the charm correctly passes it to the workload.
callback_id = str(int(time.time()))  # The slack callback id
template = r'{{ define "slack.default.callbackid" }}' + callback_id + "{{ end }}"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    # deploy charm from local source folder
    assert ops_test.model
    await ops_test.model.deploy(
        charm_under_test, resources=resources, application_name=app_name, trust=True
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    application = ops_test.model.applications[app_name]
    assert application
    assert application.units[0].workload_status == "active"
    assert await is_alertmanager_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_configure_alertmanager_with_templates(ops_test: OpsTest, httpserver):
    # define the alertmanager configuration
    assert ops_test.model
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

    # set alertmanager configuration and template file
    application = ops_test.model.applications[app_name]
    assert application
    await application.set_config(
        {"config_file": yaml.safe_dump(aconfig), "templates_file": template}
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=60)


@pytest.mark.abort_on_fail
async def test_receiver_gets_alert(ops_test: OpsTest, httpserver):
    request_from_alertmanager = None

    def request_handler(request: Request):
        """A request handler.

        Alertmanager's POST request to a slack server looks like this:

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

        # Use amtool to fire a stand-in alert
        sh.juju(  #  pyright: ignore
            [
                "ssh",
                "-m",
                ops_test.model_name,
                "--container",
                "alertmanager",
                f"{app_name}/0",
                "amtool",
                "alert",
                "add",
                "foo",
                "node=bar",
                "status=firing",
                "juju_model_uuid=1234",
                f"juju_application={app_name}",
                "juju_model=model_name",
                "--annotation=summary=summary",
            ]
        )

    # check receiver got an alert
    assert waiting.result
    assert request_from_alertmanager["attachments"][0]["callback_id"] == callback_id  # type: ignore

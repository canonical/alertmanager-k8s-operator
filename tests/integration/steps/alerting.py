# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Steps about alerts: notifications sent to receivers, and silences."""

import json
import time
from datetime import datetime, timedelta, timezone

import jubilant
import pytest
import yaml
from helpers import get_unit_address
from pytest_bdd import given, then, when
from werkzeug.wrappers import Request, Response

from src.alertmanager_client import Alertmanager
from steps.deployment import wait_for_active

RECEIVER_NAME = "fake-receiver"
CALLBACK_ID = str(int(time.time()))
TEMPLATE = r'{{ define "slack.default.callbackid" }}' + CALLBACK_ID + "{{ end }}"


def api(juju: jubilant.Juju, app: str) -> Alertmanager:
    return Alertmanager(f"http://{get_unit_address(juju, app, 0)}:9093")


@pytest.fixture
def notifications() -> dict:
    """Whether the receiver was called, and the notifications it received."""
    return {"received": [], "delivered": False}


@pytest.fixture
def silences() -> list:
    """The silences alertmanager held before the refresh."""
    return []


@given('"config_file" routes alerts to a Slack receiver and "templates_file" sets its callback ID')
def slack_receiver_with_template(juju: jubilant.Juju, app: str, httpserver):
    config = {
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
    juju.config(app, {"config_file": yaml.safe_dump(config), "templates_file": TEMPLATE})
    wait_for_active(juju, app)


@given("a silence has been created")
def silence_created(juju: jubilant.Juju, app: str, silences: list):
    start = datetime.now(timezone.utc)
    api(juju, app).set_silences(
        [{"name": "alertname", "value": "fake-alert", "isRegex": False}],
        start,
        start + timedelta(minutes=30),
    )
    silences.extend(api(juju, app).get_silences())
    assert silences, "No silences found after setting one"


@when("an alert fires")
def alert_fires(juju: jubilant.Juju, app: str, httpserver, notifications: dict):
    def handler(request: Request):
        notifications["received"].append(json.loads(request.data.decode("utf-8")))
        return Response("OK", status=200, content_type="text/plain")

    with httpserver.wait(timeout=120, raise_assertions=False) as waiting:
        httpserver.expect_oneshot_request("/", method="POST").respond_with_handler(handler)
        juju.ssh(
            f"{app}/0",
            f"amtool alert add foo node=bar status=firing juju_model_uuid=1234"
            f" juju_application={app} juju_model=model_name --annotation=summary=summary",
            container="alertmanager",
        )
    notifications["delivered"] = waiting.result


@then('the receiver gets a notification with the callback ID from "templates_file"')
def notification_has_templated_callback_id(notifications: dict):
    assert notifications["delivered"], "Alertmanager did not notify the receiver"
    assert notifications["received"][0]["attachments"][0]["callback_id"] == CALLBACK_ID


@then("alertmanager returns the same silences as before the refresh")
def same_silences(juju: jubilant.Juju, app: str, silences: list):
    assert api(juju, app).get_silences() == silences

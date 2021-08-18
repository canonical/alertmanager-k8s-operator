import hashlib
import urllib.request
from dataclasses import dataclass
from typing import Union, TypedDict, Literal, Optional

import yaml


def append_unless(unless, base, appendable):
    """
    Conditionally append one object to another. Currently the intended usage is for strings.
    :param unless: a value of base for which should not append (and return as is)
    :param base: the base value to which append
    :param appendable: the value to append to base
    :return: base, if base == unless; base + appendable, otherwise.
    """
    return base if base == unless else base + appendable


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values"""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


def fetch_url(url: str) -> Union[str, None]:
    try:
        with urllib.request.urlopen(url) as response:
            html = response.read()
            code = response.getcode()
            return html if code < 400 else None
    except:  # noqa: E722 do not use bare 'except'
        return None


class PushoverWebhookConfig(TypedDict, total=False):
    # Whether or not to notify about resolved alerts (default = true).
    send_resolved: Optional[Literal["true", "false"]]

    # The recipient user's user key.
    user_key: str

    # Your registered application's API token, see https://pushover.net/apps
    token: str

    # Notification title (default = '{{ template "pushover.default.title" . }}').
    title: Optional[str]

    # Notification message (default = '{{ template "pushover.default.message" . }}').
    message: Optional[str]

    # A supplementary URL shown alongside the message (default = '{{ template "pushover.default.url" . }}').
    url: Optional[str]

    # Priority, see https://pushover.net/api#priority (default = '{{ if eq .Status "firing" }}2{{ else }}0{{ end }}').
    priority: Optional[str]

    # How often the Pushover servers will send the same notification to the user.
    # Must be at least 30 seconds (default = 1m).
    retry: Optional[str]  # in lieu of the non-existing (analogue of) LiteralPattern['[0-9]+[smh]']

    # How long your notification will continue to be retried for, unless the user
    # acknowledges the notification (default = 1h).
    expire: Optional[
        str
    ]  # in lieu of the non-existing (analogue of) LiteralPattern['[0-9]+[smh]']

    # The HTTP client's configuration (default = global.http_config).
    http_config: Optional[str]


@dataclass
class PushoverConfig:
    name: str
    pushover_configs: PushoverWebhookConfig

    def __str__(self):
        return yaml.safe_dump(self.__dict__)

    def as_dict(self):
        return {"name": self.name, "pushover_configs": [self.pushover_configs]}

    @property
    def valid(self) -> bool:
        return bool(
            self.name
            and self.pushover_configs.get("user_key")
            and self.pushover_configs.get("token")
        )


class PagerdutyWebhookConfig(TypedDict, total=False):
    # Whether or not to notify about resolved alerts (default = true).
    send_resolved: Optional[Literal["true", "false"]]

    # The PagerDuty integration key (when using PagerDuty integration type `Prometheus`).
    service_key: str


@dataclass
class PagerdutyConfig:
    name: str
    pagerduty_configs: PagerdutyWebhookConfig

    def __str__(self):
        return yaml.safe_dump(self.__dict__)

    def as_dict(self):
        return {"name": self.name, "pagerduty_configs": [self.pagerduty_configs]}

    @property
    def valid(self) -> bool:
        return bool(self.name and self.pagerduty_configs.get("service_key"))


class GenericWebhookConfig(TypedDict, total=False):
    # Whether or not to notify about resolved alerts (default = true).
    send_resolved: Optional[Literal["true", "false"]]

    # The endpoint to send HTTP POST requests to.
    url: str

    # The HTTP client's configuration (default = global.http_config).
    http_config: Optional[str]

    # The maximum number of alerts to include in a single webhook message. Alerts
    # above this threshold are truncated. When leaving this at its default value of
    # 0, all alerts are included (default = 0).
    max_alerts: Optional[int]


@dataclass
class WebhookConfig:
    name: str
    webhook_configs: GenericWebhookConfig

    def __str__(self):
        return yaml.safe_dump(self.__dict__)

    def as_dict(self):
        return {"name": self.name, "webhook_configs": [self.webhook_configs]}

    @property
    def valid(self) -> bool:
        return bool(self.name and self.webhook_configs.get("url"))

import abc
from typing import Optional


class ConfigBase(abc.ABC):
    # TODO change to Protocol
    @staticmethod
    @abc.abstractmethod
    def from_dict(data: dict) -> Optional[dict]:
        ...

    @staticmethod
    @abc.abstractmethod
    def is_valid(data: dict) -> bool:
        ...


class ReceiverBase(ConfigBase):
    @property
    @abc.abstractmethod
    def name(self):
        ...

    @property
    @abc.abstractmethod
    def _section_name(self):
        ...

    @classmethod
    def from_dict(cls, data: dict) -> Optional[dict]:
        if not cls.is_valid(data):
            return None

        return {"name": cls.name, cls._section_name: [data]}


class PagerdutyConfig(ReceiverBase):
    name = "pagerduty"
    _section_name = "pagerduty_configs"

    @staticmethod
    def is_valid(data: dict) -> bool:
        required_keys = [
            "service_key",  # The PagerDuty integration key
        ]
        return all(data.get(key) for key in required_keys)


class PushoverConfig(ReceiverBase):
    name = "pushover"
    _section_name = "pushover_configs"

    @staticmethod
    def is_valid(data: dict) -> bool:
        required_keys = [
            "user_key",  # The recipient user's user key
            "token",  # Your registered application's API token, see https://pushover.net/apps
        ]
        return all(data.get(key) for key in required_keys)


class WebhookConfig(ReceiverBase):
    name = "webhook"
    _section_name = "webhook_configs"

    @staticmethod
    def is_valid(data: dict) -> bool:
        required_keys = [
            "url",  # The endpoint to send HTTP POST requests to
        ]
        return all(data.get(key) for key in required_keys)

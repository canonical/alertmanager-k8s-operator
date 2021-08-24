#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import abc
from typing import Optional


class ConfigBase(abc.ABC):
    """Represents the interface to configuration items coming from `config.yaml` and
    `juju config`.
    """

    # TODO change to Protocol
    @staticmethod
    @abc.abstractmethod
    def from_dict(data: dict) -> Optional[dict]:
        """Convert raw config data (e.g. :class:`ConfigData`, as in `ops.model.config`) to
        application-specific configuration format.
        """

    @staticmethod
    @abc.abstractmethod
    def is_valid(data: dict) -> bool:
        """Check that the raw config data (e.g. :class:`ConfigData`, as in `ops.model.config`)
        comprises a valid application-specific configuration.
        """


class ReceiverBase(ConfigBase):
    """Represents the interface to alertmanager receiver configuration items coming from
    `config.yaml` and `juju config`.
    """

    @property
    @abc.abstractmethod
    def name(self):
        """Class property that represents a receiver's name in an alertmanager.yml
        configuration. The same name is used in routing rules.
        """

    @property
    @abc.abstractmethod
    def _section_name(self):
        """Class property that represents a receiver's section name in an alertmanager.yml
        configuration. This is usually "<name>_configs".
        """

    @classmethod
    def from_dict(cls, data: dict) -> dict:
        if not cls.is_valid(data):
            return {}

        return {"name": cls.name, cls._section_name: [data]}


class PagerdutyConfig(ReceiverBase):
    """Utility class for converting config data into a valid pagerduty yaml section."""

    name = "pagerduty"
    _section_name = "pagerduty_configs"

    @staticmethod
    def is_valid(data: dict) -> bool:
        required_keys = [
            "service_key",  # The PagerDuty integration key
        ]
        return all(data.get(key) for key in required_keys)


class PushoverConfig(ReceiverBase):
    """Utility class for converting config data into a valid pushover yaml section."""

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
    """Utility class for converting config data into a valid webhook yaml section."""

    name = "webhook"
    _section_name = "webhook_configs"

    @staticmethod
    def is_valid(data: dict) -> bool:
        required_keys = [
            "url",  # The endpoint to send HTTP POST requests to
        ]
        return all(data.get(key) for key in required_keys)

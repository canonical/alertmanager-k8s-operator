# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Config builder for charmed alertmanager."""

import logging
from dataclasses import dataclass
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Custom exception for failed config updates."""


default_config = {
    "global": {"http_config": {"tls_config": {"insecure_skip_verify": False}}},
    "route": {
        "group_wait": "30s",
        "group_interval": "5m",
        "repeat_interval": "1h",
        "receiver": "placeholder",
    },
    "receivers": [{"name": "placeholder"}],
}


@dataclass(frozen=True)
class ConfigSuite:
    """Represents all the configuration files managed by this module, and their contents."""

    alertmanager: str
    web: Optional[str]
    templates: Optional[str]
    amtool: str


class ConfigBuilder:
    """A 'config builder' for alertmanager."""

    def __init__(
        self,
        *,
        api_port: int = 9093,
        web_route_prefix: Optional[str] = None,
    ):
        self._api_port = api_port

        # Sanitize `web_route_prefix` so it has a leading `/` and no trailing `/`
        web_route_prefix = web_route_prefix.strip("/") if web_route_prefix else ""
        self._web_route_prefix = "/" + web_route_prefix

        self._config = default_config.copy()
        self._templates = None
        self._templates_path = "/etc/alertmanager/templates.tmpl"

        self._cert_file_path = None
        self._key_file_path = None

    def set_config(self, config: Optional[dict]):
        """Set the main config file contents."""
        if config is not None:
            self._config = config
        return self

    def set_templates(self, templates: Optional[str], path: Optional[str] = None):
        """Set templates."""
        if templates is not None:
            self._templates = templates
            if path:
                self._templates_path = path
        return self

    def set_tls_server_config(self, *, cert_file_path: str, key_file_path: str):
        """Set TLS server config."""
        self._cert_file_path = cert_file_path
        self._key_file_path = key_file_path
        return self

    @property
    def _alertmanager_config(self) -> str:
        config = self._config.copy()

        # On disk, alertmanager rewrites the config and automatically adds an empty placeholder,
        # `templates: []`, so `get` is more robust than `if "templates" in config`.
        if config.get("templates"):
            logger.error(
                "alertmanager config file must not have a 'templates' section; "
                "use the 'templates' config option instead."
            )
            raise ConfigError("Invalid config file: use charm's 'templates' config option instead")

        if self._templates:
            config["templates"] = [self._templates_path]

        # add juju topology to "group_by"
        # `route` is a mandatory field so don't need to be too careful
        route = config.get("route", {})
        group_by = route.get("group_by", [])
        group_by = list(set(group_by).union(["juju_application", "juju_model", "juju_model_uuid"]))
        route["group_by"] = group_by
        config["route"] = route
        return yaml.safe_dump(config)

    @property
    def _amtool_config(self) -> str:
        # When amtool is run, it is always in the same container as alertmanager so we can use
        # `localhost` in the url.
        url = f"http://localhost:{self._api_port}" + self._web_route_prefix
        # Make sure url ends with `/`
        url = url.rstrip("/") + "/"
        return yaml.safe_dump({"alertmanager.url": url})

    @property
    def _web_config(self) -> Optional[str]:
        if self._cert_file_path and self._key_file_path:
            web_config = {
                # https://prometheus.io/docs/prometheus/latest/configuration/https/
                "tls_server_config": {
                    # Certificate and key files for server to use to authenticate to client.
                    "cert_file": self._cert_file_path,
                    "key_file": self._key_file_path,
                },
            }
            return yaml.safe_dump(web_config)
        if self._cert_file_path or self._key_file_path:
            raise ConfigError("Must provide both cert and key files")
        return None

    def build(self) -> ConfigSuite:
        """Return the entire config suite rendered."""
        return ConfigSuite(
            alertmanager=self._alertmanager_config,
            web=self._web_config,
            templates=self._templates,
            amtool=self._amtool_config,
        )

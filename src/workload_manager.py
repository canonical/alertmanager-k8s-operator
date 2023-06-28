#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload manager for grafana agent."""

import logging
import re
from typing import Dict, List, Optional, Tuple

from alertmanager_client import Alertmanager, AlertmanagerBadResponse
from ops.framework import Object
from ops.model import Container
from ops.pebble import (  # type: ignore
    ChangeError,
    ExecError,
    Layer,
)

logger = logging.getLogger(__name__)


class ConfigFileSystemState:
    """Class representing the configuration state in a filesystem."""

    def __init__(self, manifest: Optional[Dict[str, Optional[str]]] = None):
        self._manifest = manifest.copy() if manifest else {}

    @property
    def manifest(self) -> Dict[str, Optional[str]]:
        """Return a copy of the planned manifest."""
        return self._manifest.copy()

    def add_file(self, path: str, content: str):
        """Add a file to the configuration."""
        # `None` means it needs to be removed (if present). If paths changed across an upgrade,
        # to prevent stale files from remaining (if were previously written to persistent
        # storage), hard-code the old paths to None to guarantee their removal.
        self._manifest[path] = content

    def delete_file(self, path: str):
        """Add a file to the configuration."""
        self._manifest[path] = None

    def apply(self, container: Container):
        """Apply this manifest onto a container."""
        for filepath, content in self._manifest.items():
            if content is None:
                container.remove_path(filepath, recursive=True)
            else:
                container.push(filepath, content, make_dirs=True)


class WorkloadManagerError(RuntimeError):
    """Base class for exceptions raised by WorkloadManager."""


class ConfigUpdateFailure(WorkloadManagerError):
    """Custom exception for failed config updates."""


class ContainerNotReady(WorkloadManagerError):
    """Raised when an operation is run that presumes the container being ready.."""


class WorkloadManager(Object):
    """Workload manager for alertmanager."""

    _layer_name = _service_name = _exe_name = "alertmanager"

    # path, inside the workload container for alertmanager data, e.g. 'nflogs', 'silences'.
    _storage_path = "/alertmanager"

    def __init__(
        self,
        charm,
        *,
        container_name: str,
        peer_addresses: List[str],
        api_port: int,
        ha_port: int,
        web_route_prefix: str,
        external_url: str,
        config_path: str,
        web_config_path: str,
        tls_enabled: bool,
    ):
        # Must inherit from ops 'Object' to be able to register events.
        super().__init__(charm, f"{self.__class__.__name__}-{container_name}")

        self._unit = charm.unit

        self._service_name = self._container_name = container_name
        self._container = charm.unit.get_container(container_name)

        self._peer_addresses = peer_addresses

        self._api_port = api_port
        self._ha_port = ha_port
        self.api = Alertmanager(port=self._api_port, web_route_prefix=web_route_prefix)
        self._external_url = external_url
        self._config_path = config_path
        self._web_config_path = web_config_path
        self._tls_enabled = tls_enabled

        # turn the container name to a valid Python identifier
        snake_case_container_name = self._container_name.replace("-", "_")
        charm.framework.observe(
            charm.on[snake_case_container_name].pebble_ready,
            self._on_pebble_ready,
        )

    @property
    def is_ready(self):
        """Is the workload ready to be interacted with?"""
        return self._container.can_connect()

    def _on_pebble_ready(self, _):
        if version := self._alertmanager_version:
            self._unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get Alertmanager version."
            )

    @property
    def _alertmanager_version(self) -> Optional[str]:
        """Returns the version of Alertmanager.

        Returns:
            A string equal to the Alertmanager version.
        """
        if not self.is_ready:
            return None
        version_output, _ = self._container.exec([self._exe_name, "--version"]).wait_output()
        # Output looks like this:
        # alertmanager, version 0.23.0 (branch: HEAD, ...
        result = re.search(r"version (\d*\.\d*\.\d*)", version_output)
        if result is None:
            return result
        return result.group(1)

    def check_config(self) -> Tuple[str, str]:
        """Check config with amtool.

        Returns stdout, stderr.
        """
        if not self.is_ready:
            raise ContainerNotReady(
                "cannot check config: alertmanager workload container not ready"
            )
        proc = self._container.exec(["/usr/bin/amtool", "check-config", self._config_path])
        try:
            output, err = proc.wait_output()
        except ExecError as e:
            output, err = str(e.stdout), str(e.stderr)
        # let ChangeError raise
        return output, err

    def _alertmanager_layer(self) -> Layer:
        """Returns Pebble configuration layer for alertmanager."""

        def _command():
            """Returns full command line to start alertmanager."""
            # cluster listen address - empty string disables HA mode
            listen_address_arg = (
                "" if len(self._peer_addresses) == 0 else f"0.0.0.0:{self._ha_port}"
            )

            # The chosen port in the cluster.listen-address flag is the port that needs to be
            # specified in the cluster.peer flag of the other peers.
            # Assuming all replicas use the same port.
            # Sorting for repeatability in comparing between service layers.
            peer_cmd_args = " ".join(
                sorted([f"--cluster.peer={address}" for address in self._peer_addresses])
            )
            web_config_arg = (
                f"--web.config.file={self._web_config_path} " if self._tls_enabled else ""
            )
            return (
                f"{self._exe_name} "
                f"--config.file={self._config_path} "
                f"--storage.path={self._storage_path} "
                f"--web.listen-address=:{self._api_port} "
                f"--cluster.listen-address={listen_address_arg} "
                f"--web.external-url={self._external_url} "
                f"{web_config_arg}"
                f"{peer_cmd_args}"
            )

        return Layer(
            {
                "summary": "alertmanager layer",
                "description": "pebble config layer for alertmanager",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "summary": "alertmanager service",
                        "command": _command(),
                        "startup": "enabled",
                    }
                },
            }
        )

    def update_layer(self) -> bool:
        """Update service layer to reflect changes in peers (replicas).

        Returns:
          True if anything changed; False otherwise
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot update layer")

        overlay = self._alertmanager_layer()
        plan = self._container.get_plan()

        if self._service_name not in plan.services or overlay.services != plan.services:
            self._container.add_layer(self._layer_name, overlay, combine=True)
            try:
                # If a config is invalid then alertmanager would exit immediately.
                # This would be caught by pebble (default timeout is 30 sec) and a ChangeError
                # would be raised.
                self._container.replan()
                return True
            except ChangeError as e:
                logger.error(
                    "Failed to replan; pebble plan: %s; %s",
                    self._container.get_plan().to_dict(),
                    str(e),
                )
                return False

        return False

    def update_config(self, manifest: ConfigFileSystemState) -> None:
        """Update alertmanager config files to reflect changes in configuration.

        After pushing a new config, a hot-reload is attempted. If hot-reload fails, the service is
        restarted.

        Raises:
          ConfigUpdateFailure, if failed to update configuration file.
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot update config")

        logger.debug("applying config changes")
        manifest.apply(self._container)

        # Validate with amtool and raise if bad
        try:
            self.check_config()
        except WorkloadManagerError as e:
            raise ConfigUpdateFailure("Failed to validate config (run check-config action)") from e

    def restart_service(self) -> bool:
        """Helper function for restarting the underlying service.

        Returns:
            True if restart succeeded; False otherwise.
        """
        logger.info("Restarting service %s", self._service_name)

        if not self.is_ready:
            logger.error("Cannot (re)start service: container is not ready.")
            return False

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not exist,
        if not self._container.get_plan().services.get(self._service_name):
            logger.error("Cannot (re)start service: service does not (yet) exist.")
            return False

        self._container.restart(self._service_name)

        return True

    def reload(self) -> None:
        """Trigger a hot-reload of the configuration (or service restart).

        Raises:
            ConfigUpdateFailure, if the reload (or restart) fails.
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot reload")

        # Obtain a "before" snapshot of the config from the server.
        # This is different from `config` above because alertmanager adds in a bunch of details
        # such as:
        #
        #   smtp_hello: localhost
        #   smtp_require_tls: true
        #   pagerduty_url: https://events.pagerduty.com/v2/enqueue
        #   opsgenie_api_url: https://api.opsgenie.com/
        #   wechat_api_url: https://qyapi.weixin.qq.com/cgi-bin/
        #   victorops_api_url: https://alert.victorops.com/integrations/generic/20131114/alert/
        #
        # The snapshot is needed to determine if reloading took place.
        try:
            config_from_server_before = self.api.config()
        except AlertmanagerBadResponse:
            config_from_server_before = None

        # Send an HTTP POST to alertmanager to hot-reload the config.
        # This reduces down-time compared to restarting the service.
        try:
            self.api.reload()
        except AlertmanagerBadResponse as e:
            logger.warning("config reload via HTTP POST failed: %s", str(e))
            # hot-reload failed so attempting a service restart
            if not self.restart_service():
                raise ConfigUpdateFailure(
                    "Is config valid? hot reload and service restart failed."
                )

        # Obtain an "after" snapshot of the config from the server.
        try:
            config_from_server_after = self.api.config()
        except AlertmanagerBadResponse:
            config_from_server_after = None

        if config_from_server_before is None or config_from_server_after is None:
            logger.warning("cannot determine if reload succeeded")
        elif config_from_server_before == config_from_server_after:
            logger.warning("config remained the same after a reload")

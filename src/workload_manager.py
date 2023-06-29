#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload manager for grafana agent."""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple

from ops.framework import Object
from ops.model import Container
from ops.pebble import (  # type: ignore
    ChangeError,
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


class WorkloadManager(Object, ABC):
    """Workload manager for alertmanager."""

    _layer_name = _service_name = _exe_name = "alertmanager"

    # path, inside the workload container for alertmanager data, e.g. 'nflogs', 'silences'.
    _storage_path = "/alertmanager"

    def __init__(
        self,
        charm,
        *,
        container_name: str,
        external_url: str,
        config_path: str,
        tls_enabled: bool,
    ):
        # Must inherit from ops 'Object' to be able to register events.
        super().__init__(charm, f"{self.__class__.__name__}-{container_name}")

        self._unit = charm.unit

        self._service_name = self._container_name = container_name
        self._container = charm.unit.get_container(container_name)

        self._external_url = external_url
        self._config_path = config_path
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
        if version := self._version:
            self._unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get workload version."
            )

    @property
    @abstractmethod
    def _version(self) -> Optional[str]:
        """Returns the version of the workload.

        Returns:
            A string equal to the workload version.
        """
        pass

    @abstractmethod
    def check_config(self) -> Tuple[str, str]:
        """Check the configuration is valid.

        Returns stdout, stderr.
        """
        pass

    @abstractmethod
    def _workload_layer(self) -> Layer:
        """Returns Pebble configuration layer for the workload."""
        pass

    def update_layer(self) -> bool:
        """Update service layer to reflect changes in peers (replicas).

        Returns:
          True if anything changed; False otherwise
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot update layer")

        overlay = self._workload_layer()
        plan = self._container.get_plan()

        if self._service_name not in plan.services or overlay.services != plan.services:
            self._container.add_layer(self._layer_name, overlay, combine=True)
            try:
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
        """Update workload config files to reflect changes in configuration.

        After pushing a new config, a hot-reload is attempted. If hot-reload fails, the service is
        restarted. # TODO is this true for all charms?

        Raises:
          ConfigUpdateFailure, if failed to update configuration file.
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot update config")

        logger.debug("applying config changes")
        manifest.apply(self._container)

        # Validate and raise if bad
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

    @abstractmethod
    def reload(self) -> None:
        """Trigger a hot-reload of the configuration if possible (or service restart).

        Raises:
            ConfigUpdateFailure, if the reload (or restart) fails.
        """
        pass

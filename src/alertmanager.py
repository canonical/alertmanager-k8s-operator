#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Alertmanager workload manager."""

import logging
import re
from typing import List, Optional, Tuple

from alertmanager_client import Alertmanager, AlertmanagerBadResponse
from ops.pebble import ExecError, Layer

from src.workload_manager import ConfigUpdateFailure, ContainerNotReady, WorkloadManager

logger = logging.getLogger(__name__)


class AlertmanagerWorkloadManager(WorkloadManager):
    """Workload manager for Alertmanager."""

    _exe_name = "alertmanager"

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
        # Must inherit from ops 'Object to be able to register events.'
        super().__init__(
            charm=charm,
            container_name=container_name,
            external_url=external_url,
            config_path=config_path,
            tls_enabled=tls_enabled,
        )

        self._peer_addresses = peer_addresses
        self._api_port = api_port
        self._ha_port = ha_port
        self.api = Alertmanager(port=self._api_port, web_route_prefix=web_route_prefix)
        self._web_config_path = web_config_path

    def _version(self) -> Optional[str]:
        """Returns the version of Alertmanager.

        Returns:
        A string equal to the Alertmanager version.
        """
        if not self.is_ready:
            return None
        version_output, _ = self._container.exec([self._exe_name, "--version"]).wait_output()
        # Output looks like this:
        # alertmanager, version 0.23.0 (branch: HEAD, ...)
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

    def _workload_layer(self) -> Layer:
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

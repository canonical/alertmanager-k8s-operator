#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for reading values out of an output State."""

from typing import List, Optional

from ops.testing import Container, Context, State

CONTAINER_NAME = "alertmanager"
SERVICE_NAME = "alertmanager"


def container_of(state: State) -> Container:
    """The alertmanager container in the given state."""
    return state.get_container(CONTAINER_NAME)


def command_of(state: State) -> str:
    """The pebble command alertmanager is started with."""
    return container_of(state).plan.services[SERVICE_NAME].command


def cli_arg(state: State, cli_opt: str) -> Optional[str]:
    """The value of a `--flag=value` argument in the pebble command, if present."""
    for arg in command_of(state).split():
        opt_list = arg.split("=")
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None


def cluster_peers(state: State) -> List[str]:
    """The sorted `--cluster.peer` addresses in the pebble command."""
    args = command_of(state).split()
    return sorted(arg.split("=")[1] for arg in args if arg.startswith("--cluster.peer="))


def workload_path(context: Context, state: State, path: str):
    """The host-side path of a file in the workload container."""
    return container_of(state).get_filesystem(context).joinpath(path.lstrip("/"))


def workload_file(context: Context, state: State, path: str) -> str:
    """The contents of a file written to the workload container."""
    return workload_path(context, state, path).read_text()

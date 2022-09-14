#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import socket
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

PYTEST_HTTP_SERVER_PORT = 8000


@pytest.fixture(scope="module")
async def charm_under_test(ops_test: OpsTest) -> Path:
    """Charm used for integration testing."""
    path_to_built_charm = await ops_test.build_charm(".")

    return path_to_built_charm


@pytest.fixture(scope="session")
def httpserver_listen_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # ip address does not need to be reachable
        s.connect(("8.8.8.8", 1))
        local_ip_address = s.getsockname()[0]
    except Exception:
        local_ip_address = "127.0.0.1"
    finally:
        s.close()
    return local_ip_address, PYTEST_HTTP_SERVER_PORT

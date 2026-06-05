#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import socket
import subprocess
from pathlib import Path

import pytest

PYTEST_HTTP_SERVER_PORT = 8000


@pytest.fixture(scope="session")
def httpserver_listen_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # IP address does not need to be reachable; we just want the local outbound interface.
        s.connect(("8.8.8.8", 1))
        local_ip_address = s.getsockname()[0]
    except Exception:
        local_ip_address = "127.0.0.1"
    finally:
        s.close()
    return local_ip_address, PYTEST_HTTP_SERVER_PORT


@pytest.fixture(scope="session")
def charm_path() -> Path:
    """Return the path to the built charm.

    Reads CHARM_PATH from the environment when set (standard on CI).  Falls
    back to locating any pre-built ``*.charm`` file in the repository root,
    and finally builds one with ``charmcraft pack`` if none is found.
    """
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)

    existing = sorted(Path(".").glob("*.charm"))
    if existing:
        return existing[-1]

    subprocess.run(["charmcraft", "pack"], check=True)
    return sorted(Path(".").glob("*.charm"))[-1]

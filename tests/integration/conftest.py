#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import logging
import os
import socket
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

PYTEST_HTTP_SERVER_PORT = 8000
logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@pytest.fixture(scope="module")
@timed_memoizer
async def charm_under_test(ops_test: OpsTest) -> Path:
    """Charm used for integration testing."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)

    path_to_built_charm = await ops_test.build_charm(".", verbosity="debug")
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


@pytest.fixture(autouse=True, scope="module")
async def setup_env(ops_test: OpsTest):
    assert ops_test.model
    # Prevent "update-status" from interfering with the test:
    # - if fired "too quickly", traefik will flip between active/idle and maintenance;
    # - make sure charm code does not rely on update-status for correct operation.
    await ops_test.model.set_config(
        {"update-status-hook-interval": "60m", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )


@pytest.fixture(scope="module")
def temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("data")

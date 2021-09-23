#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import shutil
import tempfile
from typing import Literal

import pytest
from git import Repo

log = logging.getLogger(__name__)


async def clone_lma_bundle_and_run_its_tests(
    ops_test, charm_name: Literal["alertmanager", "prometheus", "grafana", "loki"], charm_path
):
    """Clone LMA bundle repo and run its test, but with one of the charms deployed from local.

    Args:
        ops_test: the pytest operator plugin.
        charm_name: must match one of the custom pytest arguments recognized by the lma bundle
                    tests. TODO link to the canonical repo conftest.py when merged.
        charm_path: path to the locally-built *.charm.
    """
    with tempfile.TemporaryDirectory() as temp_charm_dir:
        # Launching pytest from within pytest deletes the built *.charm because pytest-operator's
        # `build_charm()` does `rmtree` if build path already exists
        # https://github.com/charmed-kubernetes/pytest-operator/blob/main/pytest_operator/plugin.py
        # Copying the built charm elsewhere to make sure it is still available when the lma bundle
        # is being deployed.
        shutil.copy(charm_path, temp_charm_dir)
        charm_path = os.path.join(temp_charm_dir, os.path.split(charm_path)[-1])

        with tempfile.TemporaryDirectory(dir=os.getcwd()) as temp_dir:
            log.info("Cloning lma-light-bundle repo to a temp folder %s", temp_dir)
            Repo.clone_from(
                "https://github.com/canonical/lma-light-bundle.git",
                temp_dir,
                multi_options=["--single-branch"],
                branch="feature/integration_tests",  # TODO change to main after merged
                depth=1,
            )

            run_args = [
                "pytest",
                "-v",
                "--tb",
                "native",
                "--log-cli-level=INFO",
                "-s",
                f"--{charm_name}={charm_path}",
                f"{os.path.join(temp_dir, 'tests/integration')}",
            ]

            # `ops_test.run` creates a subprocess via asyncio.create_subprocess_exec
            retcode, stdout, stderr = await ops_test.run(*run_args)
            assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"
            assert 5 == 7


@pytest.mark.abort_on_fail
async def test_alertmanager_within_lma_bundle_context(ops_test):
    charm_under_test = await ops_test.build_charm(".")
    log.info("Built charm %s", charm_under_test)

    await clone_lma_bundle_and_run_its_tests(ops_test, "alertmanager", charm_under_test)

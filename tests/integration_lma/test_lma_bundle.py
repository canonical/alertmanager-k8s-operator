#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import shutil
import tempfile

import pytest
from git import Repo

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_clone_lma_bundle_and_run_its_tests(ops_test):
    charm_under_test = await ops_test.build_charm(".")
    log.info("Built charm %s", charm_under_test)

    with tempfile.TemporaryDirectory() as temp_charm_dir:
        # Launching pytest from within pytest deletes the built *.charm because pytest-operator's
        # `build_charm()` does `rmtree` if build path already exists
        # https://github.com/charmed-kubernetes/pytest-operator/blob/main/pytest_operator/plugin.py
        # Copying the built charm elsewhere to make sure it is still available when the lma bundle
        # is being deployed.
        shutil.copy(charm_under_test, temp_charm_dir)
        charm_under_test = os.path.join(temp_charm_dir, os.path.split(charm_under_test)[-1])

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
                f"--alertmanager={charm_under_test}",
                f"{os.path.join(temp_dir, 'tests/integration')}",
            ]

            # `ops_test.run` creates a subprocess via asyncio.create_subprocess_exec
            retcode, stdout, stderr = await ops_test.run(*run_args)
            assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"

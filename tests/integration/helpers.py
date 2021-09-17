# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

log = logging.getLogger(__name__)


async def cli_deploy_and_wait(
    ops_test, name: str, alias: str = "", wait_for_status: str = None, channel="edge"
):
    if not alias:
        alias = name

    run_args = [
        "juju",
        "deploy",
        "-m",
        ops_test.model_full_name,
        name,
        alias,
    ]
    if not Path(name).is_file():
        run_args.append(f"--channel={channel}")

    retcode, stdout, stderr = await ops_test.run(*run_args)
    assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"
    log.info(stdout)
    await ops_test.model.wait_for_idle(apps=[alias], status=wait_for_status, timeout=60)


async def get_unit_address(ops_test, app_name: str, unit_num: int) -> str:
    status = await ops_test.model.get_status()  # noqa: F821
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def update_status_freq(ops_test, interval: str = "10s"):
    retcode, stdout, stderr = await ops_test.run(
        "juju",
        "model-config",
        f"update-status-hook-interval={interval}",
    )
    assert (
        retcode == 0
    ), f"Changing update-status-hook-interval failed: {(stderr or stdout).strip()}"

    if stdout:
        log.info(stdout)

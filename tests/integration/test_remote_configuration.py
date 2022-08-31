#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import shutil
import time
from pathlib import Path

import helpers
import juju.errors
import pytest
import yaml
from deepdiff import DeepDiff  # type: ignore[import]
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {"alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]}

TESTER_CHARM_PATH = "./tests/integration/remote_configuration_tester"
TESTER_APP_METADATA = yaml.safe_load(
    Path(os.path.join(TESTER_CHARM_PATH, "metadata.yaml")).read_text()
)
TESTER_APP_NAME = TESTER_APP_METADATA["name"]
TESTER_APP_RESOURCES = {
    f"{TESTER_APP_NAME}-image": TESTER_APP_METADATA["resources"][f"{TESTER_APP_NAME}-image"][
        "upstream-source"
    ]
}

ALERTMANAGER_TEST_INITIAL_CONFIG = """route:
  receiver: dummy
receivers:
- name: dummy
"""


class TestAlertmanagerRemoteConfiguration:
    @pytest.fixture(scope="module")
    @pytest.mark.abort_on_fail
    async def setup(self, ops_test: OpsTest):
        charm = await ops_test.build_charm(".")
        await ops_test.model.deploy(
            charm,
            resources=RESOURCES,
            application_name=APP_NAME,
            trust=True,
        )
        await self._build_and_deploy_remote_configuration_tester_charm(ops_test)
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, TESTER_APP_NAME], status="active", timeout=1000
        )

    @pytest.mark.abort_on_fail
    async def test_given_alertmanager_not_related_to_remote_configurer_when_relation_created_then_alertmanager_configuration_is_updated_with_the_configuration_provided_by_the_remote_configurer(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        # This is the config set in the remote-configuration-tester charm augmented
        # with the defaults coming directly from the Alertmanager.
        expected_config = """global:
  resolve_timeout: 5m
  http_config:
    follow_redirects: true
  smtp_hello: localhost
  smtp_require_tls: true
  pagerduty_url: https://events.pagerduty.com/v2/enqueue
  opsgenie_api_url: https://api.opsgenie.com/
  wechat_api_url: https://qyapi.weixin.qq.com/cgi-bin/
  victorops_api_url: https://alert.victorops.com/integrations/generic/20131114/alert/
route:
  receiver: test_receiver
  group_by:
  - juju_application
  - alertname
  - juju_model_uuid
  - juju_model
  continue: false
  group_wait: 20m34s
  group_interval: 1h12m1s
  repeat_interval: 46d7h
receivers:
- name: test_receiver
templates: []
        """
        await ops_test.model.add_relation(
            relation1=f"{APP_NAME}:remote-configuration", relation2=TESTER_APP_NAME
        )
        time.sleep(5)  # 5 seconds for the Alertmanager to apply new config
        actual_config = await helpers.get_alertmanager_config(ops_test, APP_NAME, 0)
        assert (
            DeepDiff(
                yaml.safe_load(actual_config),
                yaml.safe_load(expected_config),
                ignore_order=True,
            )
            == {}
        )

    @pytest.mark.abort_on_fail
    async def test_given_alertmanager_related_to_remote_configurer_when_another_relation_created_then_juju_api_error_is_raised(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        test_app_name = "another-configurer"
        await self._build_and_deploy_remote_configuration_tester_charm(ops_test, test_app_name)
        try:
            await ops_test.model.add_relation(
                relation1=f"{APP_NAME}:remote-configuration", relation2=test_app_name
            )
            assert False
        except juju.errors.JujuError as e:
            assert True
            assert (
                e.message == 'cannot add relation "alertmanager-k8s:remote-configuration '
                f'{test_app_name}:remote-configuration": establishing a new relation for '
                "alertmanager-k8s:remote-configuration would exceed its maximum relation "
                "limit of 1"
            )

    @staticmethod
    async def _build_and_deploy_remote_configuration_tester_charm(
        ops_test: OpsTest, app_name: str = TESTER_APP_NAME
    ):
        _copy_alertmanager_remote_configuration_library_into_tester_charm()
        tester_charm = await ops_test.build_charm(TESTER_CHARM_PATH)
        await ops_test.model.deploy(
            tester_charm,
            resources=TESTER_APP_RESOURCES,
            application_name=app_name,
            trust=True,
        )
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)


def _copy_alertmanager_remote_configuration_library_into_tester_charm():
    """Ensure that the tester charm uses the current Alertmanager Remote Configuration library."""
    library_path = "lib/charms/alertmanager_k8s/v0/alertmanager_remote_configuration.py"
    install_path = "tests/integration/remote_configuration_tester/" + library_path
    shutil.copyfile(library_path, install_path)

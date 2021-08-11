# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import textwrap

import unittest
from unittest.mock import Mock, patch

import kubernetes
import ops
from charm import AlertmanagerAPIClient, AlertmanagerCharm
from ops.model import BlockedStatus
from ops.testing import Harness

from .helpers import PushPullMock, patch_network_get, tautology



# Things to test:
# - self.harness.charm._stored is updated (unless considered private impl. detail)


alertmanager_default_config = textwrap.dedent(
    """
            route:
              group_by: ['alertname']
              group_wait: 30s
              group_interval: 5m
              repeat_interval: 1h
              receiver: 'web.hook'
            receivers:
            - name: 'web.hook'
              webhook_configs:
              - url: 'http://127.0.0.1:5001/'
            inhibit_rules:
              - source_match:
                  severity: 'critical'
                target_match:
                  severity: 'warning'
                equal: ['alertname', 'dev', 'instance']
    """
)


class AlertmanagerBaseTestCase(unittest.TestCase):
    container_name: str = "alertmanager"

    def setUp(self):
        self.harness = Harness(AlertmanagerCharm)
        self.addCleanup(self.harness.cleanup)


@patch_network_get(private_address="1.1.1.1")
@patch.object(AlertmanagerAPIClient, "reload", tautology)
class TestSingleUnitAfterInitialHooks(AlertmanagerBaseTestCase):
    def setUp(self):
        super().setUp()
        self.push_pull_mock = PushPullMock()
        self.push_pull_mock.push(AlertmanagerCharm._config_path, alertmanager_default_config)

        self.relation_id = self.harness.add_relation("alerting", "otherapp")
        self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        self.harness.set_leader(True)

        network_get_patch = patch_network_get(private_address="1.1.1.1")
        # The install method only does kooky things with the Kubernetes API, so just mock the
        # return of this handler since it's invoked on every test due to begin_with_initial_hooks
        install_patch = patch("charm.AlertmanagerCharm._on_install", lambda _, event: True)

        with network_get_patch, install_patch:
            # TODO why the context is needed if we already have a class-level patch?
            self.harness.begin_with_initial_hooks()

    def test_num_peers(self):
        self.assertEqual(0, self.harness.charm.num_peers)

    def test_unit_status(self):
        # before pebble_ready, status should be "maintenance"
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.MaintenanceStatus)

        # after pebble_ready, status should be "active"
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():
            self.harness.container_pebble_ready(self.container_name)
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.ActiveStatus)

    def test_pebble_layer_added(self):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():
            self.harness.container_pebble_ready(self.container_name)
        plan = self.harness.get_container_pebble_plan(self.container_name).to_dict()

        # Check we've got the plan as expected
        self.assertIsNotNone(services := plan.get("services"))
        self.assertIsNotNone(alertmanager := services.get("alertmanager"))
        self.assertIsNotNone(command := alertmanager.get("command"))

        # Check command is as expected
        expected = self.harness.charm._alertmanager_layer()["services"]["alertmanager"]["command"]
        self.assertEqual(expected, command)

        # Check command contains key arguments
        self.assertIn("--config.file", command)
        self.assertIn("--storage.path", command)
        self.assertIn("--web.listen-address", command)
        self.assertIn("--cluster.listen-address", command)

        # Check the service was started
        service = self.harness.model.unit.get_container("alertmanager").get_service("alertmanager")
        self.assertTrue(service.is_running())

    def test_relation_data_provides_public_address(self):
        rel = self.harness.charm.framework.model.get_relation("alerting", self.relation_id)
        expected_address = "1.1.1.1:{}".format(self.harness.charm.provider.api_port)
        self.assertEqual({"public_address": expected_address}, rel.data[self.harness.charm.unit])

    def test_pagerduty_config(self):
        with self.push_pull_mock.patch_push(), self.push_pull_mock.patch_pull():
            self.harness.container_pebble_ready(self.container_name)

            for key in ["secret_service_key_42", "a_different_key_this_time"]:
                with self.subTest(key=key):
                    self.harness.update_config({"pagerduty_key": key})
                    self.assertIn(
                        "service_key: {}".format(key),
                        self.push_pull_mock.pull(self.harness.charm._config_path),
                    )

            self.harness.update_config({"pagerduty_key": ""})
            self.assertNotIn(
                "pagerduty_configs", self.push_pull_mock.pull(self.harness.charm._config_path)
            )

    def test_show_silences_action_failing(self):
        action_event = Mock(params={})
        self.harness.charm._on_show_silences_action(action_event)
        self.assertEqual(
            action_event.fail.call_args,
            [("Error retrieving silences via alertmanager api server",)],
        )

    def test_show_silences_action_succeeding(self):
        mock_silences = [
            {"id": "ab12", "status": {"state": "active"}},
            {"id": "cd34", "status": {"state": "expired"}},
        ]

        with patch.object(AlertmanagerAPIClient, "silences", lambda *args: mock_silences):
            action_event = Mock(params={"state": None})
            self.harness.charm._on_show_silences_action(action_event)
            self.assertEqual(
                action_event.set_results.call_args,
                [({"active-silences": json.dumps(mock_silences)},)],
            )

    @patch("charm.AlertmanagerCharm.namespace", "lma")
    def test_k8s_service(self):
        # with patch("charm.AlertmanagerCharm.namespace", "lma"):
        service = self.harness.charm._k8s_service
        self.assertEqual(service.metadata.name, self.harness.charm.app.name)
        self.assertEqual(service.metadata.namespace, "lma")
        self.assertEqual(
            service.metadata.labels, {"app.kubernetes.io/name": self.harness.charm.app.name}
        )
        self.assertEqual(
            service.spec.ports,
            [
                kubernetes.client.V1ServicePort(
                    name=f"{self.harness.charm._container_name}-api",
                    port=self.harness.charm._api_port,
                    target_port=self.harness.charm._api_port,
                ),
                kubernetes.client.V1ServicePort(
                    name=f"{self.harness.charm._container_name}-ha",
                    port=self.harness.charm._ha_port,
                    target_port=self.harness.charm._ha_port,
                ),
            ],
        )

    @patch("charm.AlertmanagerCharm.namespace")
    @patch("charm.AlertmanagerCharm._k8s_auth")
    @patch("charm.kubernetes.client.CoreV1Api.delete_namespaced_service")
    @patch("charm.kubernetes.client.CoreV1Api.create_namespaced_service")
    def test_patch_k8s_service(self, create, delete, auth, ns):
        ns.return_value = "lma"
        name = self.harness.charm.app.name
        create.return_value = delete.return_value = auth.return_value = True
        patched = self.harness.charm._patch_k8s_service()
        delete.assert_called_with(name=name, namespace=self.harness.charm.namespace)
        create.assert_called_with(
            namespace=self.harness.charm.namespace, body=self.harness.charm._k8s_service
        )
        self.assertEqual(patched, True)

        # Now test when we don't get authed
        auth.return_value = False
        patched = self.harness.charm._patch_k8s_service()
        # Ensure these mock calls haven't increased from the last run
        delete.assert_called_with(name=name, namespace=self.harness.charm.namespace)
        create.assert_called_with(
            namespace=self.harness.charm.namespace, body=self.harness.charm._k8s_service
        )
        self.assertEqual(patched, False)

    @patch("charm.kubernetes.client.CoreV1Api.list_namespaced_service")
    @patch("charm.AlertmanagerCharm.namespace")
    @patch("charm.kubernetes.config.load_incluster_config")
    def test_k8s_auth(self, load_config, ns, list_svc):
        ns.return_value = "lma"
        load_config.return_value = True

        authed = self.harness.charm._k8s_auth()
        list_svc.assert_called_with(namespace=self.harness.charm.namespace)
        self.assertEqual(authed, True)

        # Now test what happens when listing a svc throws an exception
        list_svc.side_effect = kubernetes.client.exceptions.ApiException(status=403)
        authed = self.harness.charm._k8s_auth()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Run `juju trust` on this application to continue"),
        )
        self.assertEqual(authed, False)


class TestAlertmanagerAPIClient(unittest.TestCase):
    def setUp(self):
        self.api = AlertmanagerAPIClient("address", 12345)

    def test_base_url(self):
        self.assertEqual("http://address:12345/", self.api.base_url)

    def test_reload_and_status(self):
        from collections import namedtuple

        Response = namedtuple("Response", ["status_code", "reason", "text", "ok"])

        # test succeess
        def mock_response(*args, **kwargs):
            return Response(200, "OK", json.dumps({"status": "fake"}), True)

        with patch("requests.post", mock_response):
            self.assertTrue(self.api.reload())

        with patch("requests.get", mock_response):
            self.assertDictEqual({"status": "fake"}, self.api.status())

        # test failure
        def mock_connection_error(*args, **kwargs):
            import requests

            raise requests.exceptions.ConnectionError

        with patch("requests.post", mock_connection_error):
            self.assertFalse(self.api.reload())

        with patch("requests.get", mock_connection_error):
            self.assertIsNone(self.api.status())

        def mock_timeout(*args, **kwargs):
            import requests

            raise requests.exceptions.ConnectTimeout

        with patch("requests.post", mock_timeout):
            self.assertFalse(self.api.reload())

        with patch("requests.get", mock_timeout):
            self.assertIsNone(self.api.status())

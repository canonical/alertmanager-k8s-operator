# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerConsumer

from ops.charm import CharmBase
from ops.framework import StoredState
from unittest.mock import patch

from typing import Dict, Callable


class DummyCharmForTestingConsumer(CharmBase):
    """A class for mimicking the bare AlertmanagerCharm functionality needed to test the consumer."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        # Must use "alerting" as the relation name because the harness parses metadata.yaml and
        # that is the relation name there (in prometheus, for example, the relation name is
        # "alertmanager" rather than "alerting").
        self.alertmanager_lib = AlertmanagerConsumer(
            self, relation_name="alerting", consumes={"alertmanager": ">0.0.0"}
        )

        self.framework.observe(
            self.alertmanager_lib.on.available, self._on_alertmanager_cluster_changed
        )

        self._stored.set_default(alertmanagers=[], on_available_emitted=0)

    def _on_alertmanager_cluster_changed(self, event):
        self._stored.on_available_emitted += 1
        self._stored.alertmanagers = self.alertmanager_lib.get_cluster_info()


def patch_network_get(private_address="10.1.157.116"):
    def network_get(*args, **kwargs):
        """patch for the not-yet-implemented testing backend needed for
        self.model.get_binding(event.relation).network.bind_address
        """
        return {
            "bind-addresses": [
                {
                    "mac-address": "",
                    "interface-name": "",
                    "addresses": [{"hostname": "", "value": private_address, "cidr": ""}],
                }
            ],
            "egress-subnets": ["10.152.183.65/32"],
            "ingress-addresses": ["10.152.183.65"],
        }

    return patch("ops.testing._TestingModelBackend.network_get", network_get)


def no_op(*args, **kwargs):
    pass


def tautology(*args, **kwargs) -> bool:
    return True


class PushPullMock:
    def __init__(self):
        self._filesystem: Dict[str, str] = {}

    def pull(self, path: str, *args, **kwargs) -> str:
        return self._filesystem.get(path, "")

    def push(self, path: str, source: str, *args, **kwargs) -> None:
        self._filesystem[path] = source

    def patch_push(self) -> Callable:
        return patch("ops.testing._TestingPebbleClient.push", self.push)

    def patch_pull(self) -> Callable:
        return patch("ops.testing._TestingPebbleClient.pull", self.pull)

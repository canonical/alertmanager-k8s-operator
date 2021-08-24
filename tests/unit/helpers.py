#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from typing import Callable, Dict
from unittest.mock import patch


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

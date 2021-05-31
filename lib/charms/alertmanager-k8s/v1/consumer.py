#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

""" # AlertmanagerConsumer library

This library is design to be used by a charm consuming the alertmanager-k8s relation.
"""


import ops
from ops.relation import ConsumerBase

import logging
from typing import List

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 1    # Must match the major version in the import path.
LIBPATCH = 0  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class AlertmanagerConsumer(ConsumerBase):
    """A one sentence summary of the class.
    This section gives more details about the class and what
    it does.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """

    def __init__(self, charm: ops.charm.CharmBase, relation_name, consumes, multi=False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self._consumer_relation_name = relation_name  # from consumer's metadata.yaml
        self._provider_relation_name = "alerting"  # from alertmanager's metadata.yaml

        # self.framework.observe(self.charm.on[self._consumer_relation_name].relation_joined,
        #                        self._on_relation_joined)

    def ip_addresses(self, event: ops.charm.RelationChangedEvent) -> List[str]:
        return event.relation.data[event.app].get("addrs", [])

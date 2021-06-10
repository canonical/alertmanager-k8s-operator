#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

""" # AlertmanagerConsumer library

This library is design to be used by a charm consuming the alertmanager-k8s relation.
"""


import ops
from ops.framework import StoredState
from ops.relation import ConsumerBase

from typing import List
import logging

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 0    # Must match the major version in the import path.
LIBPATCH = 1  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class AlertmanagerConsumer(ConsumerBase):
    """A "consumer" handler to be used by charms that relate to Alertmanager.
    This consumer auto-registers relation events on behalf of the user and communicates information
    directly via `_stored` TODO: have a documented contract and act on it in the "available" hook.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """
    _stored: StoredState

    def __init__(self, charm: ops.charm.CharmBase, relation_name, consumes, multi=False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self._consumer_relation_name = relation_name  # from consumer's metadata.yaml
        # self._provider_relation_name = "alerting"  # from alertmanager's metadata.yaml

        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_changed,
                               self._on_relation_changed)
        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_departed,
                               self._on_relation_departed)
        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_broken,
                               self._on_relation_broken)

        self._stored.set_default(alertmanagers={})

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        """This hook stores locally the address of the newly-joined alertmanager.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        if event.unit:  # event.unit may be `None` in the case of app data change
            # Save locally the public IP address of the alertmanager unit
            if address := event.relation.data[event.unit].get("public_address"):
                # TODO consider storing in unit data instead of StoredState
                self._stored.alertmanagers[event.unit.name] = address

                # inform consumer about the change
                self.on.available.emit()

    def get_cluster_info(self) -> List[str]:
        """Returns a list of ip addresses of all the alertmanager units
        """
        return sorted(list(self._stored.alertmanagers.values()))

    def _on_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        """This hook removes the address of the departing alertmanager from its local store.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        if self._stored.alertmanagers.pop(event.unit.name, None):
            # inform consumer about the change
            self.on.available.emit()

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        self._stored.alertmanagers.clear()
        # inform consumer about the change
        self.on.available.emit()

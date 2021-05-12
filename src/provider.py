#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import ops
from ops.relation import ProviderBase
from ops.framework import StoredState

import json
import logging

logger = logging.getLogger(__name__)

UNIT_ADDRESS = "{}-{}.{}-endpoints.{}.svc.cluster.local"


# TODO: name class after the relation?
class AlertingProvider(ProviderBase):

    _relation_name: str = "alerting"
    _service_name: str = "alertmanager"

    _stored = StoredState()

    def __init__(self, charm, version: str = None):
        super().__init__(charm, self._relation_name, self._service_name, version)
        self.charm = charm
        self._stored.set_default(consumers={})

        events = self.charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        pass

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        self.update_alerting(event.relation)

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        pass

    def update_alerting(self, relation):
        if self.charm.unit.is_leader():
            logger.info("Setting relation data: port")
            # if str(self.model.config["port"]) != relation.data[self.app].get("port", None):
            #     relation.data[self.app]["port"] = str(self.model.config["port"])
            relation.data[self.charm.app]["port"] = str(self.charm.model.config["port"])

            logger.info("Setting relation data: addrs")
            addrs = []
            num_units = self.charm.num_units()
            for i in range(num_units):
                addrs.append(
                    UNIT_ADDRESS.format(self.charm.meta.name, i, self.charm.meta.name, self.charm.model.name)
                )
            # if addrs != json.loads(relation.data[self.app].get("addrs", "null")):
            #     relation.data[self.app]["addrs"] = json.dumps(addrs)
            relation.data[self.charm.app]["addrs"] = json.dumps(addrs)

    def num_units(self):
        relation = self.charm.model.get_relation(self._relation_name)
        # The relation does not list ourself as a unit so we must add 1
        return len(relation.units) + 1 if relation is not None else 1

#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import ops
from ops.relation import ProviderBase
# from ops.framework import StoredState

import json
import logging

logger = logging.getLogger(__name__)


# TODO: name class after the relation?
class AlertingProvider(ProviderBase):

    # _stored = StoredState()

    def __init__(self, charm, relation_name, service_name, version: str = None):
        super().__init__(charm, relation_name, service_name, version)
        self.charm = charm
        self._relation_name = relation_name
        self._service_name = service_name
        # self._stored.set_default(consumers={})

        events = self.charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        # TODO needed in addition to _on_relation_changed?
        self.update_alerting(event.relation)

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        self.update_alerting(event.relation)

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        # TODO needed in addition to _on_relation_changed?
        self.update_alerting(event.relation)

    def update_alerting(self, relation):
        """
        Update application data bucket for the "alerting" relation
        """
        if self.charm.unit.is_leader():
            # update application data bucket with the port used by alertmanager
            logger.info("Setting relation data: port")
            # if str(self.model.config["port"]) != relation.data[self.app].get("port", None):
            #     relation.data[self.app]["port"] = str(self.model.config["port"])
            relation.data[self.charm.app]["port"] = str(self.charm.model.config["port"])

            # update application data bucket with all the unit addresses
            # From the alertmanager docs:
            #  It's important not to load balance traffic between Prometheus and its Alertmanagers,
            #  but instead, point Prometheus to a list of all Alertmanagers.
            logger.info("Setting relation data: unit_addresses")
            unit_addresses = list(map(self.charm.unit_address, range(self.charm.num_units())))
            # if unit_addresses != json.loads(relation.data[self.app].get("unit_addresses", "null")):
            #     relation.data[self.app]["unit_addresses"] = json.dumps(unit_addresses)
            logger.debug("app data bucket ['addrs']: %s", unit_addresses)
            relation.data[self.charm.app]["addrs"] = json.dumps(unit_addresses)

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
        # self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    # def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
    #     # TODO needed in addition to _on_relation_changed?
    #     self.update_alerting()

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        if self.charm.unit.is_leader():
            self.update_alerting()

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        # TODO needed in addition to _on_relation_changed?
        if self.charm.unit.is_leader():
            self.update_alerting()

    def update_alerting(self):
        """
        Update application data bucket for the "alerting" relation
        """
        # if not self.charm.unit.is_leader():
        #     return

        # update application data bucket with all the unit addresses
        # From the alertmanager docs:
        #  It's important not to load balance traffic between Prometheus and its Alertmanagers,
        #  but instead, point Prometheus to a list of all Alertmanagers.

        api_addresses = [address for address in self.charm.get_api_addresses() if address is not None]
        logger.info("Setting app data: addrs: %s", api_addresses)
        logger.info("existing 'alerting' relations: %s", self.charm.model.relations["alerting"])
        api_addresses_as_json = json.dumps(api_addresses)
        for relation in self.charm.model.relations["alerting"]:
            # unit_addresses = [address + port for address in ...]
            if api_addresses_as_json != relation.data[self.charm.app].get("addrs", "null"):
                relation.data[self.charm.app]["addrs"] = api_addresses_as_json
                logger.info("'alerting' relation data updated")

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
class AlertmanagerProvider(ProviderBase):

    # _stored = StoredState()
    _provider_relation_name = "alerting"

    def __init__(self, charm, service_name: str, version: str = None):
        super().__init__(charm, self._provider_relation_name, service_name, version)
        self.charm = charm
        self._service_name = service_name
        # self._stored.set_default(consumers={})

        events = self.charm.on[self._provider_relation_name]
        # self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    # def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
    #     # TODO needed in addition to _on_relation_changed?
    #     self.update_alerting()

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        logger.info("ALERTING RELATION CHANGED")
        if not self.charm._stored.started:
            event.defer()
            return

        if self.charm.unit.is_leader():
            self.update_alerting()

    # TODO broken or departed?
    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        logger.info("ALERTING RELATION BROKEN")
        if not self.charm._stored.started:
            event.defer()
            return

        if self.charm.unit.is_leader():
            self.update_alerting()

    def update_alerting(self):
        """
        Update application data bucket for the relation
        """
        # if not self.charm.unit.is_leader():
        #     return

        # update application data bucket with all the unit addresses
        # From the alertmanager docs:
        #  It's important not to load balance traffic between Prometheus and its Alertmanagers,
        #  but instead, point Prometheus to a list of all Alertmanagers.

        api_addresses = sorted([address for address in self.charm.get_api_addresses()
                                if address is not None])
        api_addresses_as_json = json.dumps(api_addresses)
        for relation in self.charm.model.relations[self._provider_relation_name]:
            if api_addresses_as_json != relation.data[self.charm.app].get("addrs", json.dumps([])):
                logger.info("Setting app data: addrs: %s", api_addresses)
                logger.info("existing 'alerting' relations: %s",
                            self.charm.model.relations[self._provider_relation_name])
                relation.data[self.charm.app]["addrs"] = api_addresses_as_json

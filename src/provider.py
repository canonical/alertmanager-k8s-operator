#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import ops
import ops.model
from ops.relation import ProviderBase

import logging

logger = logging.getLogger(__name__)


# TODO: name class after the relation?
class AlertmanagerProvider(ProviderBase):

    _provider_relation_name = "alerting"

    def __init__(self, charm, service_name: str, version: str = None):
        super().__init__(charm, self._provider_relation_name, service_name, version)
        self.charm = charm
        self._service_name = service_name

        events = self.charm.on[self._provider_relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_departed, self._on_relation_departed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        # "ingress-address" is auto-populated incorrectly so rolling my own, "public_address"
        event.relation.data[self.charm.unit]["public_address"] = str(
            self.model.get_binding(event.relation).network.bind_address
        )

    def _on_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        # Nothing to do here: data bags are auto-updated and relation_departed is address
        # on the consumer side.
        pass

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        # Nothing to do here: data bags are auto-updated and relation_departed is address
        # on the consumer side.
        pass

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
    """A "provider" handler to be used by the Alertmanager charm for abstracting away all the
    communication with consumers.
    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm (CharmBase): consumer charm
            service_name (str): a name for the provided service
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): the Alertmanager charm
    """
    _provider_relation_name = "alerting"

    def __init__(self, charm, service_name: str, version: str = None):
        super().__init__(charm, self._provider_relation_name, service_name, version)
        self.charm = charm
        self._service_name = service_name

        events = self.charm.on[self._provider_relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation in the
        corresponding data bag.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        # "ingress-address" is auto-populated incorrectly so rolling my own, "public_address"
        event.relation.data[self.charm.unit]["public_address"] = str(
            self.model.get_binding(event.relation).network.bind_address
        )

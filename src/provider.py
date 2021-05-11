#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from ops.relation import ProviderBase
from ops.framework import StoredState

import logging

logger = logging.getLogger(__name__)


# TODO: name class after the relation?
class AlertingProvider(ProviderBase):

    _stored = StoredState()

    def __init__(self, charm, relation_name: str, service: str, version: str = None):
        super().__init__(charm, relation_name, service, version)
        self.charm = charm
        self._stored.set_default(consumers={})

        events = self.charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_joined(self, event):
        pass

    def _on_relation_changed(self, event):
        pass

    def _on_relation_broken(self, event):
        pass


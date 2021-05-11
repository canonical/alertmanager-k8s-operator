#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from ops.relation import ConsumerBase

import logging

logger = logging.getLogger(__name__)


class AlertingConsumer(ConsumerBase):
    def __init__(self, charm, relation_name, consumes, multi=False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self.relation_name = relation_name

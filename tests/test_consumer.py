# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from .dummy import DummyCharmForTestingConsumer

from ops.testing import Harness

import unittest
# from unittest.mock import patch


class TestConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyCharmForTestingConsumer)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_relation_joined(self):
        pass

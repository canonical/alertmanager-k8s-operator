#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

import config


class TestPagerdutyConfig(unittest.TestCase):
    def test_required_keys(self):
        self.assertFalse(config.PagerdutyConfig.is_valid({}))
        self.assertFalse(config.PagerdutyConfig.is_valid({"service-key": "whatever"}))
        self.assertTrue(config.PagerdutyConfig.is_valid({"service_key": "whatever"}))

        self.assertIsNone(config.PagerdutyConfig.from_dict({}))
        self.assertIsNone(config.PagerdutyConfig.from_dict({"service-key": "whatever"}))
        self.assertIsNotNone(config.PagerdutyConfig.from_dict({"service_key": "whatever"}))

    def test_config_structure(self):
        pagerduty_config = config.PagerdutyConfig.from_dict(
            {"service_key": "whatever", "some_other_key": "John Galt"}
        )
        self.assertDictEqual(
            pagerduty_config,
            {
                "name": "pagerduty",
                "pagerduty_configs": [{"service_key": "whatever", "some_other_key": "John Galt"}],
            },
        )

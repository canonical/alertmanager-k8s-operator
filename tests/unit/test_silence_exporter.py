#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests for the stdlib silence-expiry exporter render logic."""

import unittest
from datetime import datetime, timezone

from silence_exporter import (
    _ENDSAT_METRIC,
    _SCRAPE_ERROR_METRIC,
    _parse_rfc3339,
    render_metrics,
)


def _metric_lines(exposition: str):
    return [
        line
        for line in exposition.splitlines()
        if line and not line.startswith("#")
    ]


class TestRenderMetrics(unittest.TestCase):
    def test_active_silence_emits_endsat_series(self):
        silences = [
            {
                "id": "abc-123",
                "createdBy": "alice",
                "comment": "some free text that must not leak into labels",
                "endsAt": "2024-01-02T15:04:05Z",
                "status": {"state": "active"},
            }
        ]
        out = render_metrics(silences, scrape_error=False)

        expected_epoch = datetime(
            2024, 1, 2, 15, 4, 5, tzinfo=timezone.utc
        ).timestamp()
        self.assertIn(
            f'{_ENDSAT_METRIC}{{id="abc-123",created_by="alice"}} {expected_epoch}',
            out,
        )
        # Cardinality guard: comment must never appear.
        self.assertNotIn("comment", out)
        self.assertNotIn("free text", out)
        # Self-health metric present and healthy.
        self.assertIn(f"{_SCRAPE_ERROR_METRIC} 0", out)
        # Exposition ends with a newline.
        self.assertTrue(out.endswith("\n"))

    def test_non_active_silences_are_skipped(self):
        silences = [
            {
                "id": "expired-1",
                "createdBy": "bob",
                "endsAt": "2024-01-02T15:04:05Z",
                "status": {"state": "expired"},
            },
            {
                "id": "pending-1",
                "createdBy": "bob",
                "endsAt": "2024-01-02T15:04:05Z",
                "status": {"state": "pending"},
            },
        ]
        out = render_metrics(silences, scrape_error=False)
        self.assertEqual(_metric_lines(out), [f"{_SCRAPE_ERROR_METRIC} 0"])

    def test_scrape_error_sets_health_metric(self):
        out = render_metrics([], scrape_error=True)
        self.assertIn(f"{_SCRAPE_ERROR_METRIC} 1", out)

    def test_label_values_are_escaped(self):
        silences = [
            {
                "id": 'weird"id\\',
                "createdBy": "line\nbreak",
                "endsAt": "2024-01-02T15:04:05Z",
                "status": {"state": "active"},
            }
        ]
        out = render_metrics(silences, scrape_error=False)
        self.assertIn(r'id="weird\"id\\"', out)
        self.assertIn(r'created_by="line\nbreak"', out)

    def test_unparsable_endsat_is_skipped(self):
        silences = [
            {
                "id": "bad-ts",
                "createdBy": "carol",
                "endsAt": "not-a-timestamp",
                "status": {"state": "active"},
            }
        ]
        out = render_metrics(silences, scrape_error=False)
        self.assertEqual(_metric_lines(out), [f"{_SCRAPE_ERROR_METRIC} 0"])


class TestParseRfc3339(unittest.TestCase):
    def test_zulu_suffix(self):
        self.assertEqual(
            _parse_rfc3339("2024-01-02T15:04:05Z"),
            datetime(2024, 1, 2, 15, 4, 5, tzinfo=timezone.utc).timestamp(),
        )

    def test_explicit_offset(self):
        self.assertEqual(
            _parse_rfc3339("2024-01-02T15:04:05+00:00"),
            datetime(2024, 1, 2, 15, 4, 5, tzinfo=timezone.utc).timestamp(),
        )

    def test_fractional_seconds(self):
        # Should not raise.
        self.assertIsInstance(_parse_rfc3339("2024-01-02T15:04:05.123Z"), float)


if __name__ == "__main__":
    unittest.main()

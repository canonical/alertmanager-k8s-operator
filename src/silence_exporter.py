#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Silence-expiry exporter for Alertmanager.

This script runs as a dedicated sidecar container in the Alertmanager pod. It polls the local
Alertmanager API for silences and exposes, for every *active* silence, the epoch timestamp at
which the silence ends. Prometheus can then alert when a silence is about to expire.

Design constraints:
- Standard library only. The sidecar image (a chiselled Python rock) has no pip and no extra
  packages, so this module must not import anything outside the Python standard library.
- The exporter shares the pod network namespace with the Alertmanager container, so it reaches
  the API on localhost.

Configuration is entirely via environment variables (set by the charm in the Pebble layer):
- AM_URL:          Base URL of the Alertmanager API (default "http://localhost:9093").
- EXPORTER_PORT:   Port to serve /metrics on (default 9095).
- SCRAPE_INTERVAL: Seconds between polls of the Alertmanager API (default 30).
- AM_CA_PATH:      Optional path to a CA cert used to validate the Alertmanager API when AM_URL
                   is https.
"""

import json
import logging
import os
import ssl
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional

logger = logging.getLogger("silence_exporter")

# Metric names.
_ENDSAT_METRIC = "alertmanager_silence_endsat_timestamp_seconds"
_SCRAPE_ERROR_METRIC = "alertmanager_silence_exporter_scrape_error"


def _parse_rfc3339(value: str) -> float:
    """Parse an RFC3339 / ISO8601 timestamp into epoch seconds (UTC).

    Alertmanager returns timestamps such as "2024-01-02T15:04:05.000Z" or with a numeric
    offset like "2024-01-02T15:04:05+00:00".
    """
    # datetime.fromisoformat (3.11+) understands "Z", but the sidecar image may ship an older
    # interpreter, so normalise the trailing "Z" to an explicit UTC offset first.
    normalised = value.strip()
    if normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalised)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _escape_label_value(value: str) -> str:
    """Escape a label value per the Prometheus exposition format."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics(silences: List[dict], scrape_error: bool) -> str:
    """Render the Prometheus exposition text for a list of silences.

    Only silences whose ``status.state == "active"`` produce an endsAt series.

    Cardinality guard: we deliberately expose only the ``id`` and ``created_by`` labels. The
    free-text ``comment`` field is intentionally dropped because it is high-cardinality and
    would bloat Prometheus' TSDB.
    """
    lines: List[str] = []

    lines.append(f"# HELP {_ENDSAT_METRIC} Epoch timestamp at which an active silence ends.")
    lines.append(f"# TYPE {_ENDSAT_METRIC} gauge")

    for silence in silences:
        state = (silence.get("status") or {}).get("state")
        if state != "active":
            continue

        ends_at = silence.get("endsAt")
        if not ends_at:
            continue
        try:
            ends_at_epoch = _parse_rfc3339(ends_at)
        except (ValueError, TypeError):
            logger.warning("Skipping silence with unparsable endsAt: %r", ends_at)
            continue

        silence_id = _escape_label_value(str(silence.get("id", "")))
        created_by = _escape_label_value(str(silence.get("createdBy", "")))
        lines.append(
            f'{_ENDSAT_METRIC}{{id="{silence_id}",created_by="{created_by}"}} {ends_at_epoch}'
        )

    lines.append(
        f"# HELP {_SCRAPE_ERROR_METRIC} "
        "1 if the last poll of the Alertmanager API failed, 0 otherwise."
    )
    lines.append(f"# TYPE {_SCRAPE_ERROR_METRIC} gauge")
    lines.append(f"{_SCRAPE_ERROR_METRIC} {1 if scrape_error else 0}")

    # Exposition format requires a trailing newline.
    return "\n".join(lines) + "\n"


class SilencePoller:
    """Polls the Alertmanager silences API and holds the latest rendered exposition text."""

    def __init__(self, am_url: str, ca_path: Optional[str], scrape_interval: float):
        self._silences_url = am_url.rstrip("/") + "/api/v2/silences"
        self._scrape_interval = scrape_interval
        self._lock = threading.Lock()
        # Start with an error state until the first successful scrape.
        self._exposition = render_metrics([], scrape_error=True)

        if self._silences_url.startswith("https"):
            self._ssl_context: Optional[ssl.SSLContext] = ssl.create_default_context(
                cafile=ca_path
            )
        else:
            self._ssl_context = None

    def _fetch_silences(self) -> List[dict]:
        request = urllib.request.Request(self._silences_url, method="GET")
        with urllib.request.urlopen(  # noqa: S310 (url scheme validated above)
            request, timeout=10, context=self._ssl_context
        ) as response:
            return json.loads(response.read())

    def poll_once(self) -> None:
        """Poll the API once and refresh the cached exposition text."""
        try:
            silences = self._fetch_silences()
            exposition = render_metrics(silences, scrape_error=False)
        except Exception as e:  # noqa: BLE001 - self-health metric captures any failure
            logger.warning("Failed to poll Alertmanager silences: %s", e)
            exposition = render_metrics([], scrape_error=True)

        with self._lock:
            self._exposition = exposition

    def run_forever(self) -> None:
        """Poll in a loop, sleeping ``scrape_interval`` between polls."""
        while True:
            self.poll_once()
            time.sleep(self._scrape_interval)

    @property
    def exposition(self) -> str:
        """Return the latest rendered exposition text (thread-safe)."""
        with self._lock:
            return self._exposition


def _make_handler(poller: SilencePoller):
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server naming)
            if self.path.rstrip("/") not in ("/metrics", ""):
                self.send_error(404, "Not Found")
                return
            body = poller.exposition.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 - match base signature
            # Silence the default stderr access log.
            pass

    return MetricsHandler


def main() -> None:
    """Entry point: start the poller thread and serve /metrics."""
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    am_url = os.environ.get("AM_URL", "http://localhost:9093")
    exporter_port = int(os.environ.get("EXPORTER_PORT", "9095"))
    scrape_interval = float(os.environ.get("SCRAPE_INTERVAL", "30"))
    ca_path = os.environ.get("AM_CA_PATH") or None

    logger.info(
        "Starting silence exporter: AM_URL=%s port=%s interval=%ss ca=%s",
        am_url,
        exporter_port,
        scrape_interval,
        ca_path,
    )

    poller = SilencePoller(am_url=am_url, ca_path=ca_path, scrape_interval=scrape_interval)

    poller_thread = threading.Thread(target=poller.run_forever, daemon=True)
    poller_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", exporter_port), _make_handler(poller))
    server.serve_forever()


if __name__ == "__main__":
    main()

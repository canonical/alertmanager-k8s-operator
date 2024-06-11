#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for the alertmanager charm."""

from urllib.parse import urlparse


def remove_scheme(url: str) -> str:
    """Remove the scheme from an url."""
    parsed = urlparse(url)
    return url.replace(f"{parsed.scheme}://", "", 1)

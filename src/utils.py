#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import hashlib
import urllib.request
from typing import Optional


def append_unless(unless, base, appendable):
    """
    Conditionally append one object to another. Currently the intended usage is for strings.
    :param unless: a value of base for which should not append (and return as is)
    :param base: the base value to which append
    :param appendable: the value to append to base
    :return: base, if base == unless; base + appendable, otherwise.
    """
    return base if base == unless else base + appendable


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values"""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


def fetch_url(url: str) -> Optional[str]:
    """Helper function for fetching data from a URL, that returns None instead of raising
    exceptions."""
    try:
        with urllib.request.urlopen(url) as response:
            html = response.read()
            code = response.getcode()
            return html if code < 400 else None
    except:  # noqa: E722 do not use bare 'except'
        return None

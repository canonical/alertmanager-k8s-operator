#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Configuration diffing utils."""

import hashlib
from typing import Dict, Optional, Union

from ops.model import Container


def _sha256(hashable: Union[str, bytes]) -> int:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    hex = hashlib.sha256(hashable).hexdigest()
    return int(hex, 16)


class ConfigFileSystemState:
    """Class representing the configuration state in a filesystem."""

    def __init__(self, manifest: Optional[Dict[str, Optional[str]]] = None):
        self._manifest = manifest.copy() if manifest else {}

    @property
    def manifest(self) -> Dict[str, Optional[str]]:
        """Return a copy of the planned manifest."""
        return self._manifest.copy()

    def add_file(self, path: str, content: str):
        """Add a file to the configuration."""
        # `None` means it needs to be removed (if present). If paths changed across an upgrade,
        # to prevent stale files from remaining (if were previously written to persistent
        # storage), hard-code the old paths to None to guarantee their removal.
        self._manifest[path] = content

    def delete_file(self, path: str):
        """Add a file to the configuration."""
        self._manifest[path] = None

    def __hash__(self):
        """Hash this."""
        return _sha256(str(self._manifest))

    def apply(self, container: Container):
        """Apply this manifest onto a container."""
        for filepath, content in self._manifest.items():
            if content is None:
                container.remove_path(filepath, recursive=True)
            else:
                container.push(filepath, content, make_dirs=True)

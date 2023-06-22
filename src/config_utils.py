#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Configuration diffing utils."""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import List, Union

from ops.model import Container


def _sha256(hashable) -> int:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    hex = hashlib.sha256(hashable).hexdigest()
    return int(hex, 16)


class InstructionApplyError(RuntimeError):
    """Raised when ``Instruction.apply`` fails for whatever reason."""


class _ContentFlags(str, Enum):
    """Flags for Instruction.content."""

    DELETE_RECURSIVE = "<RECURSIVELY DELETED>"
    """Recursively delete the path."""


@dataclass
class Instruction:
    """Configuration filesystem instruction."""

    path: str
    content: Union[str, _ContentFlags]


def apply(instruction: Instruction, container: Container):
    """Apply this instruction onto a container."""
    try:
        if instruction.content is _ContentFlags.DELETE_RECURSIVE:
            container.remove_path(instruction.path, recursive=True)
        else:  # str
            container.push(instruction.path, instruction.content, make_dirs=True)
    except Exception as e:
        raise InstructionApplyError from e


class ConfigFileSystemState:
    """Class representing the configuration state in a filesystem."""

    def __init__(self):
        self.instructions: List[Instruction] = []

    def add_file(self, path: str, content: str):
        """Add a file to the configuration."""
        self.instructions.append(Instruction(path, content))

    def delete_file(self, path: str):
        """Add a file to the configuration."""
        self.instructions.append(Instruction(path, _ContentFlags.DELETE_RECURSIVE))

    def __hash__(self):
        """Hash this."""
        return _sha256("".join(instruction.content for instruction in self.instructions))

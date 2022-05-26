#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""


def no_op(*args, **kwargs) -> None:
    pass


def tautology(*args, **kwargs) -> bool:
    return True

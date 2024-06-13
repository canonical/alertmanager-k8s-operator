#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for the alertmanager charm."""
from typing import List, Union
from urllib.parse import urlparse


def get_hostname_from_address(address: str) -> str:
    """Returns only the hostname from an address, omitting path, port, or scheme.

    Note that this does not work if the address provided does not include a scheme.
    """
    parsed = urlparse(address)
    if not parsed.hostname:
        raise ValueError(
            f"Error parsing address {address}, found null hostname."
            f"  urlparse(address) requires address to have a scheme."
        )
    return parsed.hostname


def add_port_to_addresses(addresses: List[str], port: Union[int, str]) -> List[str]:
    """Adds a port to all the provided addresses.

    Note that this does not check if the address already has a port.
    """
    return [f"{address}:{port}" for address in addresses]

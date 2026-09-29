#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: config files are only rewritten, and alertmanager only reloaded, on real changes."""

import dataclasses
from unittest.mock import patch

import pytest
from ops.testing import Context, State

from alertmanager import ConfigFileSystemState, WorkloadManager

CONFIG_PATH = "/etc/config.yml"
OTHER_PATH = "/etc/other.yml"


@pytest.fixture
def workload_container(context: Context, base_state: State):
    """The workload container, with an empty filesystem to push files into."""
    with context(context.on.update_status(), base_state) as mgr:
        yield mgr.charm.container


@pytest.mark.parametrize(
    "on_disk, manifest, expect_changes",
    [
        pytest.param({}, {CONFIG_PATH: "content"}, True, id="file-missing"),
        pytest.param({CONFIG_PATH: "content"}, {CONFIG_PATH: "content"}, False, id="file-same"),
        pytest.param(
            {CONFIG_PATH: "old content"}, {CONFIG_PATH: "new content"}, True, id="file-differs"
        ),
        # A manifest entry of `None` means the file should be removed.
        pytest.param({CONFIG_PATH: "content"}, {CONFIG_PATH: None}, True, id="stale-file-present"),
        pytest.param({}, {CONFIG_PATH: None}, False, id="stale-file-absent"),
        pytest.param(
            {CONFIG_PATH: "content", OTHER_PATH: "content"},
            {CONFIG_PATH: "content", OTHER_PATH: "content"},
            False,
            id="many-files-same",
        ),
        pytest.param(
            {CONFIG_PATH: "old content", OTHER_PATH: "content"},
            {CONFIG_PATH: "new content", OTHER_PATH: "content"},
            True,
            id="many-files-one-differs",
        ),
    ],
)
def test_has_changes_compares_the_manifest_against_the_container(
    workload_container, on_disk, manifest, expect_changes
):
    # GIVEN a container with these files on disk
    for path, content in on_disk.items():
        workload_container.push(path, content, make_dirs=True)

    # WHEN the wanted manifest is compared against it
    # THEN it reports whether anything needs writing
    assert ConfigFileSystemState(manifest).has_changes(workload_container) is expect_changes


def test_alertmanager_is_reloaded_when_the_config_changes(context: Context, base_state: State):
    # GIVEN a charm whose config differs from what is on disk
    state_in = dataclasses.replace(
        base_state, config={"config_file": "global:\n  resolve_timeout: 10m\n"}
    )

    # WHEN the charm reconciles
    with patch.object(WorkloadManager, "reload") as reload:
        context.run(context.on.config_changed(), state_in)

    # THEN alertmanager is reloaded to pick up the new config
    reload.assert_called_once()

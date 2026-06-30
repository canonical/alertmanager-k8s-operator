#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for config change detection."""

import dataclasses
import unittest
from unittest.mock import MagicMock, patch

import ops
import pytest
from helpers import begin_with_initial_hooks_isolated
from ops.pebble import PathError

from alertmanager import ConfigFileSystemState, WorkloadManager

ops.testing.SIMULATE_CAN_CONNECT = True  # pyright: ignore
CONTAINER_NAME = "alertmanager"


class TestConfigFileSystemStateHasChanges(unittest.TestCase):
    """Tests for ConfigFileSystemState.has_changes()."""

    def setUp(self):
        self.container = MagicMock()
        # has_changes() uses `with container.pull(p) as f: f.read()`, so make the
        # pull result a context manager that yields itself; tests configure .read on it.
        pull_result = self.container.pull.return_value
        pull_result.__enter__.return_value = pull_result
        pull_result.__exit__.return_value = False

    def test_file_does_not_exist(self):
        """A file that doesn't exist in the container is a change."""
        self.container.pull.side_effect = PathError("not found", "not found")
        manifest = ConfigFileSystemState({"/etc/config.yml": "content"})
        self.assertTrue(manifest.has_changes(self.container))

    def test_file_exists_with_same_content(self):
        """A file with identical content is not a change."""
        self.container.pull.return_value.read.return_value = "content"
        manifest = ConfigFileSystemState({"/etc/config.yml": "content"})
        self.assertFalse(manifest.has_changes(self.container))

    def test_file_exists_with_different_content(self):
        """A file with different content is a change."""
        self.container.pull.return_value.read.return_value = "old content"
        manifest = ConfigFileSystemState({"/etc/config.yml": "new content"})
        self.assertTrue(manifest.has_changes(self.container))

    def test_file_should_be_removed_and_exists(self):
        """A file marked for removal that still exists is a change."""
        self.container.pull.return_value.read.return_value = "content"
        manifest = ConfigFileSystemState({"/etc/config.yml": None})
        self.assertTrue(manifest.has_changes(self.container))

    def test_file_should_be_removed_and_does_not_exist(self):
        """A file marked for removal that is already gone is not a change."""
        self.container.pull.side_effect = PathError("not found", "not found")
        manifest = ConfigFileSystemState({"/etc/config.yml": None})
        self.assertFalse(manifest.has_changes(self.container))

    def test_multiple_files_no_changes(self):
        """Multiple files all matching is not a change."""
        self.container.pull.return_value.read.return_value = "content"
        manifest = ConfigFileSystemState({
            "/etc/config.yml": "content",
            "/etc/other.yml": "content",
        })
        self.assertFalse(manifest.has_changes(self.container))

    def test_multiple_files_one_change(self):
        """One differing file among many is a change."""
        def pull_side_effect(path):
            mock = MagicMock()
            mock.__enter__.return_value = mock
            mock.__exit__.return_value = False
            if path == "/etc/config.yml":
                mock.read.return_value = "old content"
            else:
                mock.read.return_value = "content"
            return mock

        self.container.pull.side_effect = pull_side_effect
        manifest = ConfigFileSystemState({
            "/etc/config.yml": "new content",
            "/etc/other.yml": "content",
        })
        self.assertTrue(manifest.has_changes(self.container))


class TestCharmReloadConditional:
    """Tests that charm only reloads when config actually changes."""

    @pytest.fixture
    def initial_state(self, context):
        return begin_with_initial_hooks_isolated(context, leader=True)

    def test_common_exit_hook_reloads_on_config_change(self, context, initial_state):
        """_common_exit_hook reloads when config changes."""
        with patch.object(WorkloadManager, "reload") as mock_reload:
            # Change config from default
            state = dataclasses.replace(
                initial_state,
                config={"config_file": "global:\n  resolve_timeout: 10m\n"}
            )
            state = context.run(context.on.config_changed(), state)
            # Config changed from default, so reload should be called
            mock_reload.assert_called_once()

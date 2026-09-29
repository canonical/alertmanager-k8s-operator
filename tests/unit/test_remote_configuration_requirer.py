# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: alertmanager can take its config from a relation instead of from charm config."""

import dataclasses
import json
from typing import cast

import pytest
import yaml
from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
    DEFAULT_RELATION_NAME,
)
from deepdiff import DeepDiff  # type: ignore[import]
from helpers import workload_file
from ops.model import BlockedStatus
from ops.testing import Context, Relation, State

TEST_ALERTMANAGER_DEFAULT_CONFIG = """route:
  receiver: placeholder
receivers:
- name: placeholder
"""
TEST_ALERTMANAGER_REMOTE_CONFIG = """receivers:
- name: test_receiver
route:
  receiver: test_receiver
  group_by:
  - alertname
  group_wait: 1234s
  group_interval: 4321s
  repeat_interval: 1111h
"""


def remote_configuration(**app_data) -> Relation:
    """A relation over which a provider publishes an alertmanager config."""
    return Relation(
        DEFAULT_RELATION_NAME, remote_app_name="remote-config-provider", remote_app_data=app_data
    )


@pytest.fixture
def remote_config() -> dict:
    return yaml.safe_load(TEST_ALERTMANAGER_REMOTE_CONFIG)


def test_a_config_from_the_relation_is_rendered_with_juju_topology(
    context: Context, base_state: State, alertmanager_charm, remote_config
):
    # GIVEN a provider publishing a valid alertmanager config
    relation = remote_configuration(alertmanager_config=json.dumps(remote_config))
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN the workload runs that config, with juju topology merged into its grouping
    expected = dict(remote_config)
    route = cast(dict, expected.get("route", {}))
    route["group_by"] = list(
        set(route.get("group_by", [])).union(["juju_application", "juju_model", "juju_model_uuid"])
    )
    expected["route"] = route

    rendered = yaml.safe_load(workload_file(context, state, alertmanager_charm._config_path))
    assert DeepDiff(rendered, expected, ignore_order=True) == {}


def test_charm_blocks_when_config_comes_from_both_the_relation_and_charm_config(
    context: Context, base_state: State, remote_config
):
    # GIVEN a provider publishing a config AND a user-provided config
    relation = remote_configuration(alertmanager_config=json.dumps(remote_config))
    state_in = dataclasses.replace(
        base_state,
        relations=[*base_state.relations, relation],
        config={"config_file": TEST_ALERTMANAGER_DEFAULT_CONFIG},
    )

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN the charm blocks rather than silently picking one
    assert state.unit_status == BlockedStatus("Multiple configs detected")


def test_an_invalid_config_from_the_relation_is_not_rendered(
    context: Context, base_state: State, alertmanager_charm
):
    # GIVEN a provider publishing an invalid alertmanager config
    relation = remote_configuration(
        alertmanager_config=json.dumps(yaml.safe_load("some: invalid_config"))
    )
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN the invalid config does not reach the workload
    rendered = yaml.safe_load(workload_file(context, state, alertmanager_charm._config_path))
    assert "some" not in rendered


def test_templates_from_the_relation_are_written_to_the_workload(
    context: Context, base_state: State, alertmanager_charm, remote_config
):
    # GIVEN a provider publishing both a config and a template
    template = '{{define "myTemplate"}}do something{{end}}'
    relation = remote_configuration(
        alertmanager_config=json.dumps(remote_config),
        alertmanager_templates=json.dumps([template]),
    )
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the charm reconciles
    state = context.run(context.on.relation_changed(relation), state_in)

    # THEN the template is written to the workload
    assert workload_file(context, state, alertmanager_charm._templates_path) == template

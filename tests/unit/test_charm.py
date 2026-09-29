#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the charm renders its workload config and publishes its address."""

import dataclasses

import pytest
import yaml
from helpers import CONTAINER_NAME, command_of, workload_path
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.testing import Context, Relation, State


def rendered_config(context: Context, state: State, alertmanager_charm) -> dict:
    return yaml.safe_load(
        workload_path(context, state, alertmanager_charm._config_path).read_text()
    )


def test_peer_relation_has_no_other_units(context: Context, base_state: State):
    # GIVEN a single-unit deployment
    # WHEN the charm reconciles
    with context(context.on.config_changed(), base_state) as mgr:
        mgr.run()

        # THEN the peer relation exists but has no peers
        assert mgr.charm.peer_relation is not None
        assert len(mgr.charm.peer_relation.units) == 0


def test_pebble_layer_starts_alertmanager_with_the_expected_arguments(
    context: Context, base_state: State
):
    # GIVEN a ready charm
    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), base_state)

    # THEN the alertmanager service is running
    container = state.get_container(CONTAINER_NAME)
    assert container.services["alertmanager"].is_running()

    # AND its command carries the key arguments
    command = command_of(state)
    for arg in (
        "--config.file",
        "--storage.path",
        "--web.listen-address",
        "--cluster.listen-address",
    ):
        assert arg in command


def test_alerting_relation_data_advertises_the_unit_address(
    context: Context, base_state: State, alertmanager_charm, fqdn
):
    # GIVEN a charm related to a consumer over "alerting"
    relation = Relation("alerting", remote_app_name="otherapp")
    state_in = dataclasses.replace(base_state, relations=[*base_state.relations, relation])

    # WHEN the consumer joins
    state = context.run(context.on.relation_joined(relation, remote_unit=0), state_in)

    # THEN it publishes its url, address and scheme to the consumer
    port = alertmanager_charm._ports.api
    local_unit_data = state.get_relation(relation.id).local_unit_data
    assert {
        "url": local_unit_data["url"],
        "public_address": local_unit_data["public_address"],
        "scheme": local_unit_data["scheme"],
    } == {
        "url": f"http://{fqdn}:{port}",
        "public_address": f"{fqdn}:{port}",
        "scheme": "http",
    }


def test_juju_topology_is_added_to_a_user_config_without_group_by(
    context: Context, base_state: State, alertmanager_charm
):
    # GIVEN a user-provided config that does not set "group_by"
    state_in = dataclasses.replace(
        base_state,
        config={"config_file": yaml.dump({"not a real config": "but good enough for testing"})},
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the user's config is preserved
    config = rendered_config(context, state, alertmanager_charm)
    assert config["not a real config"] == "but good enough for testing"

    # AND juju topology is grouped on
    assert sorted(config["route"]["group_by"]) == sorted(
        ["juju_model", "juju_application", "juju_model_uuid"]
    )


def test_juju_topology_is_merged_into_a_user_provided_group_by(
    context: Context, base_state: State, alertmanager_charm
):
    # GIVEN a user-provided config that already sets "group_by"
    state_in = dataclasses.replace(
        base_state,
        config={"config_file": yaml.dump({"route": {"group_by": ["alertname", "juju_model"]}})},
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN juju topology is merged into the user's grouping
    config = rendered_config(context, state, alertmanager_charm)
    assert sorted(config["route"]["group_by"]) == sorted(
        ["alertname", "juju_model", "juju_application", "juju_model_uuid"]
    )


def test_juju_topology_is_not_added_when_group_by_is_ellipsis(
    context: Context, base_state: State, alertmanager_charm
):
    """The special value '...' effectively disables aggregation entirely.

    Ref: https://prometheus.io/docs/alerting/latest/configuration/#route
    """
    # GIVEN a user-provided config that disables aggregation
    state_in = dataclasses.replace(
        base_state, config={"config_file": yaml.dump({"route": {"group_by": ["..."]}})}
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the grouping is left untouched
    config = rendered_config(context, state, alertmanager_charm)
    assert config["route"]["group_by"] == ["..."]


def test_charm_blocks_when_the_user_config_declares_templates(context: Context, base_state: State):
    # GIVEN a user-provided config that declares a "templates" section
    state_in = dataclasses.replace(
        base_state, config={"config_file": yaml.dump({"templates": ["/what/ever/*.tmpl"]})}
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the charm blocks
    assert isinstance(state.unit_status, BlockedStatus)


def test_charm_unblocks_when_the_templates_section_is_removed(
    context: Context, base_state: State
):
    # GIVEN a blocked charm, because its config declares a "templates" section
    state_in = dataclasses.replace(
        base_state, config={"config_file": yaml.dump({"templates": ["/what/ever/*.tmpl"]})}
    )
    state = context.run(context.on.config_changed(), state_in)
    assert isinstance(state.unit_status, BlockedStatus)

    # WHEN the offending section is removed
    state = dataclasses.replace(state, config={"config_file": yaml.dump({})})
    state = context.run(context.on.config_changed(), state)

    # THEN the charm goes active again
    assert isinstance(state.unit_status, ActiveStatus)


def test_templates_file_is_not_written_without_a_user_config(
    context: Context, base_state: State, alertmanager_charm
):
    # GIVEN templates but no config file
    state_in = dataclasses.replace(
        base_state,
        config={
            "config_file": "",
            "templates_file": '{{ define "some.tmpl.variable" }}whatever it is{{ end}}',
        },
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN no templates file is written to the workload
    assert not workload_path(context, state, alertmanager_charm._templates_path).exists()


def test_templates_are_written_and_referenced_when_a_user_config_is_set(
    context: Context, base_state: State, alertmanager_charm
):
    # GIVEN both a user config and templates
    templates = '{{ define "some.tmpl.variable" }}whatever it is{{ end}}'
    state_in = dataclasses.replace(
        base_state,
        config={
            "config_file": yaml.dump({"route": {"group_by": ["alertname", "juju_model"]}}),
            "templates_file": templates,
        },
    )

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN the templates are written to the workload
    assert workload_path(context, state, alertmanager_charm._templates_path).read_text() == (
        templates
    )

    # AND the rendered config points at them
    config = rendered_config(context, state, alertmanager_charm)
    assert config["templates"] == [alertmanager_charm._templates_path]


def test_charm_is_in_maintenance_while_the_container_is_unreachable(
    context: Context, base_state: State
):
    # GIVEN a charm whose workload container is not up yet
    container = dataclasses.replace(base_state.get_container(CONTAINER_NAME), can_connect=False)
    state_in = dataclasses.replace(base_state, containers=[container])

    # WHEN the charm reconciles
    state = context.run(context.on.config_changed(), state_in)

    # THEN it waits in maintenance
    assert isinstance(state.unit_status, MaintenanceStatus)


def test_charm_is_active_once_the_container_is_reachable(context: Context, base_state: State):
    # GIVEN a charm whose workload container is up
    # WHEN pebble reports the container ready
    state = context.run(
        context.on.pebble_ready(base_state.get_container(CONTAINER_NAME)), base_state
    )

    # THEN the charm goes active
    assert isinstance(state.unit_status, ActiveStatus)


@pytest.fixture
def tls_paths(alertmanager_charm):
    return {
        alertmanager_charm._server_cert_path,
        alertmanager_charm._ca_cert_path,
        alertmanager_charm._key_path,
    }


def test_show_config_action_omits_certificates_that_are_not_on_disk(
    context: Context, base_state: State, alertmanager_charm, tls_paths
):
    # GIVEN a charm whose config has been rendered, but with no certificates on disk
    started = context.run(context.on.config_changed(), base_state)
    config = workload_path(context, started, alertmanager_charm._config_path).read_text()

    # WHEN the "show-config" action runs
    with context(context.on.action("show-config"), started) as mgr:
        # AND GIVEN that config is on disk
        mgr.charm.container.push(alertmanager_charm._config_path, config, make_dirs=True)
        mgr.run()

    # THEN the action reports the config
    results = context.action_results
    assert results is not None
    assert results.keys() == {"path", "content", "configs"}

    # AND no certificate files are listed
    paths_rendered = {entry["path"] for entry in yaml.safe_load(results["configs"])}
    assert not tls_paths & paths_rendered


def test_show_config_action_reports_certificates_that_are_on_disk(
    context: Context, base_state: State, alertmanager_charm, tls_paths
):
    # GIVEN a charm whose config has been rendered
    started = context.run(context.on.config_changed(), base_state)
    config = workload_path(context, started, alertmanager_charm._config_path).read_text()

    # AND certificate files are on disk
    with context(context.on.action("show-config"), started) as mgr:
        mgr.charm.container.push(alertmanager_charm._config_path, config, make_dirs=True)
        for filepath in tls_paths:
            mgr.charm.container.push(filepath, "test", make_dirs=True)

        # WHEN the "show-config" action runs
        mgr.run()

    # THEN the action reports the config
    results = context.action_results
    assert results is not None
    assert results.keys() == {"path", "content", "configs"}

    # AND every certificate file is listed
    paths_rendered = {entry["path"] for entry in yaml.safe_load(results["configs"])}
    assert tls_paths <= paths_rendered

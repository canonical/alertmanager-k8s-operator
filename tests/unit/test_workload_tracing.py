# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for workload tracing support."""

import dataclasses
import json

import yaml
from helpers import begin_with_initial_hooks_isolated
from ops.testing import Context, Relation

from config_builder import ConfigBuilder


class TestConfigBuilderWorkloadTracing:
    """Unit tests for ConfigBuilder.set_workload_tracing."""

    def test_no_tracing_section_when_endpoint_is_none(self):
        # GIVEN a ConfigBuilder with no tracing endpoint
        # WHEN the config is built
        config_yaml = (
            ConfigBuilder()
            .set_workload_tracing(endpoint=None, ca_cert_path="")
            .build()
            .alertmanager
        )
        config = yaml.safe_load(config_yaml)

        # THEN no 'tracing' key is present
        assert "tracing" not in config

    def test_tracing_section_injected_for_http_endpoint(self):
        # GIVEN a ConfigBuilder with a plain HTTP tracing endpoint URL
        # WHEN the config is built
        endpoint = "http://tempo-0.tempo.svc.cluster.local:4318/v1/traces"
        config_yaml = (
            ConfigBuilder()
            .set_workload_tracing(endpoint=endpoint, ca_cert_path="")
            .build()
            .alertmanager
        )
        config = yaml.safe_load(config_yaml)

        # THEN a 'tracing' section is present with host:port only, insecure=true, no tls_config
        assert config["tracing"] == {
            "client_type": "http",
            "endpoint": "tempo-0.tempo.svc.cluster.local:4318",
            "sampling_fraction": 1.0,
            "insecure": True,
        }
        assert "tls_config" not in config["tracing"]

    def test_tracing_section_uses_ca_file_for_https_endpoint(self):
        # GIVEN a ConfigBuilder with an HTTPS tracing endpoint and a CA cert path
        endpoint = "https://tempo.svc.cluster.local:4318/v1/traces"
        ca_path = "/etc/ssl/certs/ca-certificates.crt"
        config_yaml = (
            ConfigBuilder()
            .set_workload_tracing(endpoint=endpoint, ca_cert_path=ca_path)
            .build()
            .alertmanager
        )
        config = yaml.safe_load(config_yaml)

        # THEN the tracing section has host:port endpoint, insecure=false, tls_config.ca_file
        assert config["tracing"]["endpoint"] == "tempo.svc.cluster.local:4318"
        assert config["tracing"]["insecure"] is False
        assert config["tracing"]["tls_config"] == {"ca_file": ca_path}

    def test_tracing_section_absent_when_set_workload_tracing_not_called(self):
        # GIVEN a ConfigBuilder where set_workload_tracing is never called
        # WHEN the config is built
        config_yaml = ConfigBuilder().build().alertmanager
        config = yaml.safe_load(config_yaml)

        # THEN no 'tracing' key is present
        assert "tracing" not in config


_TRACING_HTTP_APP_DATA = json.dumps(
    [
        {
            "protocol": {"name": "otlp_http", "type": "http"},
            "url": "http://tempo-0.tempo-endpoints.cos.svc.cluster.local:4318/v1/traces",
        }
    ]
)

_TRACING_HTTPS_APP_DATA = json.dumps(
    [
        {
            "protocol": {"name": "otlp_http", "type": "http"},
            "url": "https://tempo-0.tempo-endpoints.cos.svc.cluster.local:4318/v1/traces",
        }
    ]
)


class TestOtelResourceAttributes:
    """Tests that OTEL_RESOURCE_ATTRIBUTES is set in the Pebble layer environment."""

    def test_otel_resource_attributes_present_in_pebble_layer(self, context: Context):
        # GIVEN a running alertmanager
        state = begin_with_initial_hooks_isolated(context)

        # WHEN update_status fires
        state_out = context.run(context.on.update_status(), state)

        # THEN the alertmanager pebble layer includes OTEL_RESOURCE_ATTRIBUTES
        container = state_out.get_container("alertmanager")
        plan = container.plan
        env = plan.services["alertmanager"].environment
        assert "OTEL_RESOURCE_ATTRIBUTES" in env

    def test_otel_resource_attributes_includes_juju_topology(self, context: Context):
        # GIVEN a running alertmanager
        state = begin_with_initial_hooks_isolated(context)

        # WHEN update_status fires
        state_out = context.run(context.on.update_status(), state)

        # THEN OTEL_RESOURCE_ATTRIBUTES contains all required Juju topology keys
        container = state_out.get_container("alertmanager")
        plan = container.plan
        env = plan.services["alertmanager"].environment
        otel_attrs = env["OTEL_RESOURCE_ATTRIBUTES"]
        assert "juju_application=" in otel_attrs
        assert "juju_model=" in otel_attrs
        assert "juju_model_uuid=" in otel_attrs
        assert "juju_unit=" in otel_attrs
        assert "juju_charm=" in otel_attrs


class TestWorkloadTracingScenario:
    """Scenario-level tests for the workload tracing integration."""

    def test_no_tracing_in_config_without_relation(self, context: Context):
        # GIVEN an alertmanager charm running without a tracing relation
        state = begin_with_initial_hooks_isolated(context)

        # WHEN update_status fires
        state_out = context.run(context.on.update_status(), state)

        # THEN the alertmanager config written to the container has no 'tracing' section
        container = state_out.get_container("alertmanager")
        config = yaml.safe_load(
            container.get_filesystem(context)
            .joinpath("etc/alertmanager/alertmanager.yml")
            .read_text()
        )
        assert "tracing" not in config

    def test_http_tracing_endpoint_injected_into_config(self, context: Context):
        # GIVEN an alertmanager charm with a tracing relation providing an HTTP OTLP endpoint
        state = begin_with_initial_hooks_isolated(context)
        tracing_rel = Relation(
            "tracing",
            remote_app_data={"receivers": _TRACING_HTTP_APP_DATA},
        )
        state = dataclasses.replace(state, relations={*state.relations, tracing_rel})

        # WHEN relation-changed fires for the tracing relation
        state_out = context.run(context.on.relation_changed(tracing_rel), state)

        # THEN the alertmanager config has a tracing section with the full URL, no tls_config
        container = state_out.get_container("alertmanager")
        config = yaml.safe_load(
            container.get_filesystem(context)
            .joinpath("etc/alertmanager/alertmanager.yml")
            .read_text()
        )
        assert "tracing" in config
        assert config["tracing"]["client_type"] == "http"
        assert (
            config["tracing"]["endpoint"] == "tempo-0.tempo-endpoints.cos.svc.cluster.local:4318"
        )
        assert config["tracing"]["insecure"] is True
        assert "tls_config" not in config["tracing"]
        assert "insecure" in config["tracing"]

    def test_https_tracing_endpoint_uses_ca_file(self, context: Context):
        # GIVEN an alertmanager charm with a tracing relation providing an HTTPS OTLP endpoint
        state = begin_with_initial_hooks_isolated(context)
        tracing_rel = Relation(
            "tracing",
            remote_app_data={"receivers": _TRACING_HTTPS_APP_DATA},
        )
        state = dataclasses.replace(state, relations={*state.relations, tracing_rel})

        # WHEN relation-changed fires
        state_out = context.run(context.on.relation_changed(tracing_rel), state)

        # THEN the tracing section has tls_config.ca_file pointing to the charm CA cert path,
        # not an insecure flag — TLS is verified via the system CA bundle
        container = state_out.get_container("alertmanager")
        config = yaml.safe_load(
            container.get_filesystem(context)
            .joinpath("etc/alertmanager/alertmanager.yml")
            .read_text()
        )
        assert "tracing" in config
        assert (
            config["tracing"]["endpoint"] == "tempo-0.tempo-endpoints.cos.svc.cluster.local:4318"
        )
        assert config["tracing"]["insecure"] is False
        assert "tls_config" in config["tracing"]
        assert "ca_file" in config["tracing"]["tls_config"]
        assert "insecure" in config["tracing"]

    def test_tracing_removed_from_config_on_relation_broken(self, context: Context):
        # GIVEN an alertmanager charm with a tracing relation in place
        state = begin_with_initial_hooks_isolated(context)
        tracing_rel = Relation(
            "tracing",
            remote_app_data={"receivers": _TRACING_HTTP_APP_DATA},
        )
        state = dataclasses.replace(state, relations={*state.relations, tracing_rel})
        state = context.run(context.on.relation_changed(tracing_rel), state)

        # Verify tracing is present before breaking
        container = state.get_container("alertmanager")
        config_before = yaml.safe_load(
            container.get_filesystem(context)
            .joinpath("etc/alertmanager/alertmanager.yml")
            .read_text()
        )
        assert "tracing" in config_before

        # WHEN the tracing relation is broken
        # Use the relation object from the output state (context.run returns new objects).
        # The relation must remain in state — ops/juju semantics require the relation to be
        # present during relation_broken (it departs *during* the event, not before).
        current_tracing_rel = next(r for r in state.relations if r.endpoint == "tracing")
        state_out = context.run(context.on.relation_broken(current_tracing_rel), state)

        # THEN the tracing section is removed from the config
        container = state_out.get_container("alertmanager")
        config_after = yaml.safe_load(
            container.get_filesystem(context)
            .joinpath("etc/alertmanager/alertmanager.yml")
            .read_text()
        )
        assert "tracing" not in config_after

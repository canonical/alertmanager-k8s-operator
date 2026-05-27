Feature: Workload tracing

  Alertmanager emits OTLP traces to a Tempo backend.
  Juju topology labels are attached to every span via OTEL_RESOURCE_ATTRIBUTES.

  Scenario: Alertmanager sends traces over plain HTTP
    Given alertmanager and tempo are deployed
    When alertmanager is related to tempo for workload tracing
    Then alertmanager and tempo reach active status
    And hitting the healthy endpoint produces a trace in tempo

  Scenario: Alertmanager sends traces over TLS
    Given alertmanager, tempo, and self-signed-certificates are deployed
    And alertmanager is related to self-signed-certificates for TLS
    When alertmanager is related to tempo for workload tracing
    Then alertmanager and tempo reach active status
    And hitting the healthy endpoint produces a trace in tempo

Feature: Workload tracing over TLS

  Alertmanager emits OTLP traces to a Tempo backend over TLS.
  The CA certificate from self-signed-certificates is passed to Alertmanager's
  tls_config so that the TLS handshake can be verified.
  Juju topology labels are attached to every span via OTEL_RESOURCE_ATTRIBUTES.

  Scenario: Alertmanager sends traces over TLS
    Given alertmanager, tempo, and self-signed-certificates are deployed
    And alertmanager is related to self-signed-certificates for TLS
    When alertmanager is related to tempo for workload tracing
    Then alertmanager and tempo reach active status
    And hitting the healthy endpoint produces a trace in tempo

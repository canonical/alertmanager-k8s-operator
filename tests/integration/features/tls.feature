Feature: TLS across refreshes
  Alertmanager keeps serving its API over HTTPS when the charm is refreshed.
  The baseline TLS behaviour comes from observability-features' tls.feature.

  Scenario: The workload API stays on HTTPS after a refresh
    Given the charm is deployed
    And a certificates provider is deployed
    And the charm is integrated with the certificates provider
    When the charm is refreshed
    Then the workload API is served over HTTPS

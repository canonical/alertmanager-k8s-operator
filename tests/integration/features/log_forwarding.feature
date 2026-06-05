Feature: Log forwarding

  Alertmanager forwards its logs to Loki for centralized log aggregation
  and analysis within the observability stack.

  Scenario: Alertmanager logs are forwarded to Loki
    Given alertmanager and loki are deployed
    When alertmanager is related to loki for logging
    Then alertmanager and loki reach active status
    And alertmanager logs are queryable in loki

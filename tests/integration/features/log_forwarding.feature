Feature: Log forwarding
  Once integrated with Loki, Alertmanager forwards its logs to it, labelled with
  its Juju topology.

  Scenario: Alertmanager logs reach Loki
    Given the "alertmanager" application is deployed
    And Loki is deployed
    When the "alertmanager" application is integrated with Loki
    Then Loki has logs from the "alertmanager" application

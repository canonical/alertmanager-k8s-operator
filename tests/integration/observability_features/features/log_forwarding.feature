Feature: Log forwarding
  Once integrated with Loki, the charm forwards its workload logs to it,
  labelled with the charm's Juju topology.

  Scenario: Workload logs reach Loki
    Given the charm is deployed
    And Loki is deployed
    When the charm is integrated with Loki
    Then Loki has logs from the charm

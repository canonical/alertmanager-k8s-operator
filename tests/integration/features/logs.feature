Feature: Log forwarding
  Alertmanager forwards its logs to Loki over "logging".

  Background:
    Given alertmanager is deployed

  Scenario: Loki receives alertmanager's logs
    When alertmanager is related to Loki over "logging"
    Then Loki has logs from alertmanager

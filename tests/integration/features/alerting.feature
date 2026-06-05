Feature: Alerting

  Alertmanager receives alerts from Prometheus and dispatches notifications
  to configured receivers based on the routing rules.

  Scenario: Alertmanager receives alerts from Prometheus
    Given alertmanager and prometheus are deployed
    When prometheus is related to alertmanager for alerting
    Then alertmanager and prometheus reach active status
    And alertmanager receives alerts from prometheus

  Scenario: Alertmanager dispatches notifications to a webhook receiver
    Given alertmanager is deployed with a webhook receiver configured
    When an alert is triggered
    Then alertmanager sends a notification to the webhook

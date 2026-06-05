Feature: Persistence

  Alertmanager silences and notification state persist across
  restarts and upgrades using attached storage.

  Scenario: Silences persist across charm upgrades
    Given alertmanager is deployed
    And a silence is configured
    When the charm is upgraded
    Then the silence is still active

  Scenario: Silences persist across pod restarts
    Given alertmanager is deployed
    And a silence is configured
    When the alertmanager pod is deleted
    Then alertmanager recovers to active status
    And the silence is still active

  Scenario: Notification state persists across restarts
    Given alertmanager is deployed with a configured receiver
    When an alert is triggered and acknowledged
    And the alertmanager pod is restarted
    Then the notification state is preserved

Feature: Resilience

  Alertmanager recovers gracefully from infrastructure failures
  including pod deletions and container restarts.

  Scenario: Alertmanager recovers from pod deletion
    Given alertmanager is deployed and active
    When the alertmanager pod is deleted via kubectl
    Then alertmanager recovers to active status
    And the alertmanager API is responsive

  Scenario: Alertmanager recovers from container restart
    Given alertmanager is deployed and active
    When the alertmanager container is restarted
    Then alertmanager recovers to active status
    And the alertmanager API is responsive

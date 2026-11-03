Feature: Operations
  A deployed alertmanager is healthy, and recovers when Kubernetes recreates
  its pod.

  Background:
    Given alertmanager is deployed

  Scenario: A deployed alertmanager is healthy
    Then alertmanager is healthy

  Scenario: Alertmanager recovers after its pod is deleted
    When the alertmanager pod is deleted
    Then alertmanager is healthy

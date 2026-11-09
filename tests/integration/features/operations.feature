Feature: Operations
  A deployed alertmanager is healthy, recovers when Kubernetes recreates its
  pod, and stays healthy and keeps its silences when it is refreshed from its
  Charmhub release to the local charm.

  Scenario: A deployed alertmanager is healthy
    Given alertmanager is deployed
    Then alertmanager is healthy

  Scenario: Alertmanager recovers after its pod is deleted
    Given alertmanager is deployed
    When the alertmanager pod is deleted
    Then alertmanager is healthy

  Scenario: Alertmanager stays healthy through an upgrade
    Given alertmanager is deployed from Charmhub
    When alertmanager is refreshed to the local charm
    Then alertmanager is healthy

  Scenario: Silences survive an upgrade
    Given alertmanager is deployed from Charmhub
    And a silence has been created
    When alertmanager is refreshed to the local charm
    Then alertmanager returns the same silences as before the refresh

Feature: Upgrade

  Alertmanager can be upgraded to newer versions while preserving
  configuration and maintaining service availability.

  Scenario: Alertmanager upgrades in isolation
    Given alertmanager is deployed from charmhub
    When alertmanager is refreshed with a local charm
    Then alertmanager reaches active status
    And the alertmanager API is responsive

  Scenario: Alertmanager upgrades with relations intact
    Given alertmanager is deployed with prometheus and karma relations
    When alertmanager is refreshed with a local charm
    Then alertmanager and all related charms reach active status
    And all relations remain functional

  Scenario: Multi-unit alertmanager upgrades gracefully
    Given alertmanager is deployed with multiple units and relations
    When alertmanager is refreshed with a local charm
    Then all alertmanager units reach active status
    And the cluster remains healthy

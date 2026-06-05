Feature: High availability

  Alertmanager supports native clustering for high availability.
  Multiple units form a cluster and synchronize silences and notifications.

  Scenario: Alertmanager units form a cluster
    Given alertmanager is deployed with multiple units
    Then all alertmanager units reach active status
    And all units are part of the same cluster

  Scenario: Silences are replicated across cluster members
    Given alertmanager is deployed with multiple units
    When a silence is created on one unit
    Then the silence is visible on all units

  Scenario: Cluster survives leader change
    Given alertmanager is deployed with multiple units
    When the leader unit is removed
    Then a new leader is elected
    And alertmanager reaches active status

  Scenario: Scaling down preserves cluster health
    Given alertmanager is deployed with multiple units
    When alertmanager is scaled down
    Then the remaining units reach active status
    And the cluster remains healthy

  Scenario: Scaling up adds units to the cluster
    Given alertmanager is deployed with one unit
    When alertmanager is scaled up
    Then all units reach active status
    And all units are part of the same cluster

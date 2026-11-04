Feature: High-availability clustering
  Alertmanager stays healthy as it is scaled up or down, including when a
  scale-down removes the leader.

  Scenario Outline: Alertmanager stays healthy when it is scaled
    Given alertmanager has <before> units
    When alertmanager is scaled to <after> units
    Then alertmanager is healthy

    Examples:
      | before | after |
      | 1      | 3     |
      | 3      | 1     |

  Scenario: Alertmanager stays healthy when a scale-down removes the leader
    Given alertmanager has 3 units
    And the leader is not unit 0
    When alertmanager is scaled to 1 unit
    Then alertmanager is healthy

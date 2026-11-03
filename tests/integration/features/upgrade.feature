# Skipped: the Charmhub release targets ubuntu@24.04 while the local charm
# targets ubuntu@26.04, and `juju refresh` cannot cross bases.
@skip
Feature: Upgrade
  Refreshing alertmanager from its Charmhub release to the local charm keeps it
  healthy, and keeps the silences stored on its persistent volume.

  Background:
    Given alertmanager is deployed from Charmhub

  Scenario: Alertmanager stays healthy through a refresh
    When alertmanager is refreshed to the local charm
    Then alertmanager is healthy

  Scenario Outline: Alertmanager related to Prometheus and Karma stays healthy through a refresh
    Given alertmanager has <units> units
    And alertmanager is related to Prometheus over "alerting"
    And alertmanager is related to Karma over "karma-dashboard"
    When alertmanager is refreshed to the local charm
    Then alertmanager is healthy

    Examples:
      | units |
      | 1     |
      | 2     |

  Scenario: Silences survive a refresh
    Given a silence has been created
    When alertmanager is refreshed to the local charm
    Then alertmanager returns the same silences as before the refresh

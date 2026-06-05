Feature: Karma dashboard

  Alertmanager integrates with Karma to provide an enhanced
  multi-cluster alert dashboard experience.

  Scenario: Alertmanager is registered with Karma dashboard
    Given alertmanager and karma are deployed
    When alertmanager is related to karma for karma-dashboard
    Then alertmanager and karma reach active status
    And karma displays alerts from alertmanager

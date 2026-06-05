Feature: Self-monitoring

  Alertmanager exposes metrics and dashboards for monitoring
  its own health and performance within the COS ecosystem.

  Scenario: Alertmanager metrics are scraped by Prometheus
    Given alertmanager and prometheus are deployed
    When prometheus is related to alertmanager for self-metrics-endpoint
    Then alertmanager and prometheus reach active status
    And prometheus scrapes alertmanager metrics

  Scenario: Alertmanager dashboards are provisioned in Grafana
    Given alertmanager and grafana are deployed
    When alertmanager is related to grafana for grafana-dashboard
    Then alertmanager and grafana reach active status
    And alertmanager dashboards are available in grafana

  Scenario: Alertmanager is listed in the COS catalogue
    Given alertmanager and catalogue are deployed
    When alertmanager is related to catalogue
    Then alertmanager appears as an item in the catalogue

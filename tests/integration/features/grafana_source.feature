Feature: Grafana datasource

  Alertmanager can be configured as a Grafana datasource to allow
  querying alerts and silences directly from Grafana dashboards.

  Scenario: Alertmanager is registered as a single Grafana datasource
    Given alertmanager and grafana are deployed
    When alertmanager is related to grafana for grafana-source
    Then alertmanager and grafana reach active status
    And exactly one alertmanager datasource is available in grafana

  Scenario: Scaling alertmanager does not create duplicate datasources
    Given alertmanager and grafana are deployed and related
    When alertmanager is scaled to multiple units
    Then exactly one alertmanager datasource is available in grafana

  Scenario: Alertmanager datasource works through ingress
    Given alertmanager, grafana, and traefik are deployed
    When alertmanager is related to traefik for ingress
    And alertmanager is related to grafana for grafana-source
    Then alertmanager and grafana reach active status
    And the alertmanager datasource URL uses the ingress endpoint

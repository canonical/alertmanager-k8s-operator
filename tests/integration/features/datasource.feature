Feature: Grafana datasource
  Alertmanager registers itself as a datasource in Grafana over
  "grafana-source". The datasource is served by the ingress when there is one,
  and by the Kubernetes service otherwise.

  Background:
    Given alertmanager has 2 units
    And alertmanager is related to Grafana over "grafana-source"

  Scenario: Grafana gets one datasource for all the units
    Then Grafana has a single datasource for alertmanager

  Scenario: Without ingress, the datasource is served by the Kubernetes service
    Given alertmanager has no ingress relation
    Then the datasource is served by alertmanager's Kubernetes service

  Scenario: With ingress, the datasource is served by the ingress
    Given alertmanager is related to Traefik over "ingress"
    Then the datasource is served by alertmanager's ingress

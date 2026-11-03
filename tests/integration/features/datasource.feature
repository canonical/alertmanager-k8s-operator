Feature: Grafana datasource
  Alertmanager registers one Grafana datasource, however many units it has. It
  points at the Kubernetes service without ingress, and elsewhere with it.

  Background:
    Given alertmanager has 2 units
    And alertmanager is related to Grafana over "grafana-source"

  Scenario: Without ingress, the datasource is the Kubernetes service
    Given alertmanager has no ingress relation
    Then Grafana has one datasource for alertmanager, at its Kubernetes service URL

  Scenario: With ingress, the datasource is no longer the Kubernetes service
    Given alertmanager is related to Traefik over "ingress"
    Then Grafana has one datasource for alertmanager, not at its Kubernetes service URL

Feature: TLS
  Once integrated with a certificates provider, Alertmanager serves its API over
  HTTPS, with a certificate issued by that provider for each unit's FQDN.

  Background:
    Given the "alertmanager" application is deployed
    And a certificates provider is deployed

  Scenario: Alertmanager serves its API over HTTPS
    When the "alertmanager" application is integrated with the certificates provider
    Then the "alertmanager" application serves HTTPS on port 9093

  Scenario: Alertmanager keeps serving HTTPS after a refresh
    Given the "alertmanager" application is integrated with the certificates provider
    When the "alertmanager" application is refreshed
    Then the "alertmanager" application serves HTTPS on port 9093

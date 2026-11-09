Feature: Server TLS
  With a certificate from a CA over "certificates", alertmanager serves HTTPS
  for the unit's in-cluster FQDN, and keeps doing so after a refresh.

  Background:
    Given alertmanager is deployed
    And alertmanager is related to a CA over "certificates"

  Scenario: The server certificate names the unit's in-cluster FQDN
    Then the certificate alertmanager serves names the unit's in-cluster FQDN

  Scenario: Alertmanager answers over HTTPS
    Then alertmanager answers over HTTPS, verified against the CA

  Scenario: Alertmanager still answers over HTTPS after a refresh
    When alertmanager is refreshed to the local charm
    Then alertmanager answers over HTTPS, verified against the CA

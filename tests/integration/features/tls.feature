Feature: TLS

  Alertmanager supports TLS encryption for its web interface
  when integrated with a certificate provider.

  Scenario: Alertmanager serves HTTPS with TLS certificates
    Given alertmanager and self-signed-certificates are deployed
    When alertmanager is related to self-signed-certificates for certificates
    Then alertmanager and self-signed-certificates reach active status
    And alertmanager serves HTTPS on port 9093
    And the certificate has valid SANs

  Scenario: TLS certificates are renewed automatically
    Given alertmanager is deployed with TLS enabled
    When the certificate expires
    Then a new certificate is requested
    And alertmanager continues serving HTTPS

  Scenario: Alertmanager trusts received CA certificates
    Given alertmanager is deployed
    When alertmanager receives CA certificates via receive-ca-cert
    Then the CA certificates are installed in the trust store

Feature: TLS
  Once integrated with a certificates provider, the charm serves its workload API
  over HTTPS, with a certificate issued by that provider for each unit's FQDN.

  Scenario: The workload API is served over HTTPS
    Given the charm is deployed
    And a certificates provider is deployed
    When the charm is integrated with the certificates provider
    Then the workload API is served over HTTPS

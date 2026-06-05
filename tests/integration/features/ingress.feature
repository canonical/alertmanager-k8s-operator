Feature: Ingress

  Alertmanager can be exposed through an ingress controller like Traefik
  for external access with proper path handling.

  Scenario: Alertmanager is accessible through Traefik ingress
    Given alertmanager and traefik are deployed
    When alertmanager is related to traefik for ingress
    Then alertmanager and traefik reach active status
    And alertmanager is accessible through the ingress URL

  Scenario: Ingress URL is propagated to related charms
    Given alertmanager, traefik, and prometheus are deployed
    When alertmanager is related to traefik for ingress
    And prometheus is related to alertmanager for alerting
    Then prometheus receives the ingress URL for alertmanager

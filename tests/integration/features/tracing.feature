Feature: Tracing
  Alertmanager sends traces to the Tempo it is related to: those of the
  requests its workload serves over "tracing", whether it serves over HTTP or
  HTTPS, and those of the charm's own operation over "charm-tracing".

  Scenario Outline: Tempo receives alertmanager's workload traces
    Given alertmanager serves over <scheme>
    And alertmanager is related to Tempo over "tracing"
    When a request is made to alertmanager's API
    Then Tempo has workload traces from alertmanager

    Examples:
      | scheme |
      | HTTP   |
      | HTTPS  |

  Scenario: Tempo receives alertmanager's charm traces
    Given alertmanager is deployed
    And alertmanager is related to Tempo over "charm-tracing"
    Then Tempo has charm traces from alertmanager

Feature: Workload tracing
  Alertmanager sends traces of the requests it serves to the Tempo it is
  related to over "tracing", whether it serves over HTTP or HTTPS.

  Scenario Outline: Tempo receives alertmanager's traces
    Given alertmanager serves over <scheme>
    And alertmanager is related to Tempo over "tracing"
    When a request is made to alertmanager's API
    Then Tempo has traces from alertmanager

    Examples:
      | scheme |
      | HTTP   |
      | HTTPS  |

Feature: Configuration
  Alertmanager can be configured through the `config_file` and
  `templates_file` options, and applies them to the notifications it sends.

  Background:
    Given alertmanager is deployed

  Scenario: Alertmanager applies the configuration it is given
    Given "config_file" routes alerts to a Slack receiver and "templates_file" sets its callback ID
    When an alert fires
    Then the receiver gets a notification with the callback ID from "templates_file"

Feature: Configuration
  Alertmanager notifies the receivers set in `config_file`, rendered with the
  templates set in `templates_file`.

  Background:
    Given alertmanager is deployed

  Scenario: Notifications are rendered with the operator's templates
    Given "config_file" routes alerts to a Slack receiver and "templates_file" sets its callback ID
    When an alert fires
    Then the receiver gets a notification with the callback ID from "templates_file"

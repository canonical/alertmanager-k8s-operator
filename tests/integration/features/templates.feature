Feature: Alert templates

  Alertmanager supports custom Go templates for customizing
  notification content sent to receivers.

  Scenario: Custom templates are applied to notifications
    Given alertmanager is deployed with custom templates
    When an alert triggers a notification
    Then the notification uses the custom template formatting

  Scenario: Templates can be updated at runtime
    Given alertmanager is deployed with custom templates
    When the templates_file config is updated
    Then alertmanager reloads the templates
    And subsequent notifications use the new template

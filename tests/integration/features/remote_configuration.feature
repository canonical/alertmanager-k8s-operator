Feature: Remote configuration

  Alertmanager can receive its configuration from a remote charm
  instead of using local juju config, enabling dynamic configuration management.

  Scenario: Alertmanager uses configuration from a remote provider
    Given alertmanager and a remote configuration provider are deployed
    When alertmanager is related to the provider for remote-configuration
    Then alertmanager and the provider reach active status
    And alertmanager uses the configuration from the provider

  Scenario: Local config blocks when remote configuration is active
    Given alertmanager is related to a remote configuration provider
    When local config_file is set
    Then alertmanager enters blocked status
    And the status message indicates configuration conflict

  Scenario: Removing remote configuration relation restores local control
    Given alertmanager is related to a remote configuration provider
    When the remote-configuration relation is removed
    Then alertmanager can use local config_file again

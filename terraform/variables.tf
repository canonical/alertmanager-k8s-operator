variable "config_options" {
  description = "Configuration options for the charm"

  type = object({
    app_name           = optional(string, "alertmanager")  # Name to give the deployed application
    channel            = string                            # Channel that the application is deployed from
    config             = optional(map(string), {})         # Map of the application configuration options
    # FIXME: Passing an empty constraints value to the Juju Terraform provider currently
    # causes the operation to fail due to https://github.com/juju/terraform-provider-juju/issues/344
    constraints        = optional(string, "arch=amd64")    # String listing constraints for this application
    model              = string                            # Reference to an existing model resource or data source for the model to deploy to
    revision           = optional(number, null)            # Revision number of the application
    storage_directives = optional(map(string), {})         # Storage directives (constraints) for the application
    trust              = optional(bool, true)              # Set the trust for the application.
    units              = optional(number, 1)               # Unit count/scale
  })
}

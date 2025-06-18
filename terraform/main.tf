resource "juju_application" "alertmanager" {
  name               = var.config_options.app_name
  config             = var.config_options.config
  constraints        = var.config_options.constraints
  model              = var.model
  storage_directives = var.config_options.storage_directives
  trust              = var.config_options.trust
  units              = var.config_options.units

  charm {
    name     = "alertmanager-k8s"
    channel  = var.config_options.channel
    revision = var.config_options.revision
  }
}

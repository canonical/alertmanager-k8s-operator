resource "juju_application" "alertmanager" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  resources          = var.resources
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    base     = var.base
    name     = "alertmanager-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
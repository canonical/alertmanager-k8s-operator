resource "juju_application" "alertmanager" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "alertmanager-k8s"
    channel  = var.channel
    revision = var.revision
  }

  resources = {
    "alertmanager-image" : "ubuntu/alertmanager@sha256:0a7be6fa837357c3076838ae08fdedfcbf70901a0b35cbf3945c967c9f5bfccf"
  }
}
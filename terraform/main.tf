resource "juju_application" "alertmanager" {
  name  = var.app_name
  model = var.model_name
  trust = true
  charm {
    name     = "alertmanager-k8s"
    channel  = var.channel
    revision = var.revision
  }
  config = var.config
}
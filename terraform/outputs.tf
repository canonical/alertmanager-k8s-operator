output "app_name" {
  value = juju_application.alertmanager.name
}

output "provides" {
  value = {
    alerting              = "alerting"
    karma_dashboard       = "karma-dashboard"
    self_metrics_endpoint = "self-metrics-endpoint"
    grafana_dashboard     = "grafana-dashboard"
    grafana_source        = "grafana-source"
  }
}

output "requires" {
  value = {
    catalogue            = "catalogue",
    certificates         = "certificates",
    ingress              = "ingress",
    tracing              = "tracing",
    remote_configuration = "remote-configuration"
  }
}

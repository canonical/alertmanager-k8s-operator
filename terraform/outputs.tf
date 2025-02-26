output "app_name" {
  value = juju_application.alertmanager.name
}

output "endpoints" {
  value = {
    # Requires
    catalogue            = "catalogue",
    certificates         = "certificates",
    ingress              = "ingress",
    tracing              = "tracing",
    remote_configuration = "remote-configuration"

    # Provides
    alerting              = "alerting"
    karma_dashboard       = "karma-dashboard"
    self_metrics_endpoint = "self-metrics-endpoint"
    grafana_dashboard     = "grafana-dashboard"
    grafana_source        = "grafana-source"
  }
}

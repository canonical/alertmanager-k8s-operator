output "app_name" {
  value = juju_application.alertmanager.name
}

output "provides" {
  value = {
    alerting              = "alerting"
    karma_dashboard       = "karma-dashboard"
    provide_cmr_mesh      = "provide-cmr-mesh"
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
    logging              = "logging",
    remote_configuration = "remote-configuration",
    require_cmr_mesh     = "require-cmr-mesh",
    service_mesh         = "service-mesh",
    tracing              = "tracing",
  }
}

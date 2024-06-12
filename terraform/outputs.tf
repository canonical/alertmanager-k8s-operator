# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.alertmanager.name
}

# Required integration endpoints

output "ingress_endpoint" {
  description = "Name of the endpoint used by Alertmanager for the ingress configuration."
  value       = "ingress"
}

output "remote_configuration_endpoint" {
  description = "Name of the endpoint which allows other applications to configure Alertmanager."
  value       = "remote-configuration"
}

output "catalogue_endpoint" {
  description = "Name of the endpoint used by Alertmanager for the Catalogue integration."
  value       = "catalogue"
}

output "certificates_endpoint" {
  description = "Name of the endpoint used to integrate with the TLS certificates provider."
  value       = "certificates"
}

# Provided integration endpoints

output "alerting_endpoint" {
  description = "Name of the endpoint used by Alertmanager for handling alerts sent by client applications."
  value       = "alerting"
}

output "karma_dashboard_endpoint" {
  description = "Name of the endpoint used to link an entire Alertmanager cluster to a Karma dashboard."
  value       = "karma-dashboard"
}

output "metrics_endpoint" {
  description = "Exposes the Prometheus metrics endpoint providing telemetry about the Alertmanager instance."
  value       = "self-metrics-endpoint"
}

output "grafana_dashboard_endpoint" {
  description = "Forwards the built-in Grafana dashboard(s) for monitoring Alertmanager."
  value       = "grafana-dashboard"
}

output "grafana_source_endpoint" {
  description = "Name of the endpoint used by Alertmanager to create a datasource in Grafana."
  value       = "grafana-source"
}

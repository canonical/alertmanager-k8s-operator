# Integrating alertmanager-k8s

Alermanager can handle different types of relations in the `provides` side and in the `requires` side.

## Provides

### Alerting

```yaml
  alerting:
    interface: alertmanager_dispatch
```

Over the the
[`alertmanager_dispatch`](https://charmhub.io/alertmanager-k8s/libraries/alertmanager_dispatch)
relation interface Alermanager can be related to charms that can forward alerts to it,
for example: [Prometheus][Prometheus operator], [Loki][Loki operator].

```
juju relate alertmanager-k8s:alerting prometheus-k8s:alerting
```

### Karma dashboard

```yaml
  karma-dashboard:
    interface: karma_dashboard
```

The [`karma_dashboard`](https://charmhub.io/karma-k8s/libraries/karma_dashboard)
relation interface links an entire Alertmanager cluster to a
[Karma](https://charmhub.io/karma-k8s) dashboard.
Scaling alertmanager would automatically cause karma to group alerts by
cluster.

```
juju relate alertmanager-k8s:karma_dashboard karma-k8s:karma_dashboard
```

### Self metrics endpoint


```yaml
self-metrics-endpoint:
    interface: prometheus_scrape
```
This Alertmanager charm may forward information about its metrics endpoint and associated alert rules to a Prometheus charm over the `self-metrics-endpoint` relation using the [`prometheus_scrape`](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) interface. In order for these metrics to be aggregated by the remote Prometheus charm all that is required is to relate the two charms as in:

```bash
juju relate alertmanager-k8s:self-metrics-endpoint prometheus:metrics-endpoint
```


### Grafana dashboard

```yaml
  grafana-dashboard:
    interface: grafana_dashboard
```

Over the `grafana-dashboard` relation using the [`grafana-dashboard`](https://charmhub.io/grafana-k8s/libraries/grafana_dashboard) interface, this Alertmanager charm also provides meaningful dashboards about its metrics to be shown in a [Grafana Charm ](https://charmhub.io/grafana-k8s).

In order to add these dashboards to Grafana all that is required is to relate the two charms in the following way:

```bash
juju relate alertmanager-k8s:grafana-dashboard grafana-k8s:grafana-dashboard
```

### Grafana Source

```yaml
  grafana-source:
    interface: grafana_datasource
```

This charm may provide a data source to Grafana through the `grafana-source` relation using the [`grafana_datasource`](https://charmhub.io/grafana-k8s/libraries/grafana_source) interface.

```
juju relate alertmanager-k8s:grafana-source grafana-k8s:grafana-source
```

## Requires


### Ingress

```yaml
  ingress:
    interface: ingress
    limit: 1
```

Interactions with the Alertmanager charm can not be assumed to originate within the same Juju model, let alone the same Kubernetes cluster, or even the same Juju cloud. Hence the charm also supports an Ingress relation.

Alertmanager typically needs a "per app" Ingress.  The ingress relation is available in the [traefik-k8s](https://charmhub.io/traefik-k8s) charm and this Alertmanager charm does support that relation over [`ingress`](https://charmhub.io/traefik-k8s/libraries/ingress) interface.


```
juju relate alertmanager-k8s:ingress traefik-k8s:ingress
```

[Loki operator]: https://charmhub.io/loki-k8s
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[Karma operator]: https://charmhub.io/karma-k8s/

# Integrating alertmanager-k8s

## Provides

### alertmanager_dispatch

Any charm that implements the
[`alertmanager_dispatch`](https://charmhub.io/alertmanager-k8s/libraries/alertmanager_dispatch)
relation interface can be related to this charm for forwarding alerts to alertmanager,
for example: [Prometheus][Prometheus operator], [Loki][Loki operator].

```
juju relate alertmanager-k8s prometheus-k8s
```

### karma_dashboard
The [`karma_dashboard`](https://charmhub.io/karma-k8s/libraries/karma_dashboard)
relation interface links an entire Alertmanager cluster to a
[Karma][Karma operator] dashboard.
Scaling alertmanager would automatically cause karma to group alerts by
cluster.

```
juju relate alertmanager-k8s karma-k8s
```

## Requires
None.

[Loki operator]: https://charmhub.io/loki-k8s
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[Karma operator]: https://charmhub.io/karma-k8s/

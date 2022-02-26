# Alertmanager Operator (k8s)

[![Test Suite](https://github.com/canonical/alertmanager-k8s-operator/actions/workflows/ci.yaml/badge.svg)](https://github.com/canonical/alertmanager-k8s-operator/actions/workflows/ci.yaml)

## Description

The [Alertmanager] operator provides an alerting solution for the
[Prometheus][Prometheus Docs] [Operator][Prometheus Operator]. It is part of an
Observability stack in the [Juju] charm [ecosystem]. Alertmanager accepts
alerts from Prometheus, then deduplicates, groups and routes them to the
selected receiver, based on a set of alerting rules. These alerting rules may
be set by any supported [charm] that uses the services of Prometheus by forming
a relation with it.

[Alertmanager]: https://prometheus.io/docs/alerting/latest/alertmanager/
[Prometheus Docs]: https://prometheus.io/docs/introduction/overview/
[Prometheus Operator]: https://github.com/canonical/prometheus-operator
[Juju]: https://jaas.ai/
[ecosystem]: https://charmhub.io/
[charm]: https://charmhub.io/

## Usage
```shell
juju deploy alertmanager-k8s
juju config alertmanager-k8s \
  config_file='@path/to/alertmanager.yml' \
  templates_file='@path/to/templates.tmpl'
```

### Configuration

See [config.yaml](config.yaml) for the full details.

#### `config_file`
Use this option to pass your own alertmanager configuration file:

```shell
juju deploy alertmanager-k8s --config config_file='@path/to/alertmanager.yml'
```

or after deployment:

```shell
`juju config alertmanager-k8s config_file='@path/to/alertmanager.yml'`
```

Refer to the
[official documentation](https://www.prometheus.io/docs/alerting/latest/configuration/)
for full details.

Note that the configuration file must not have a `templates` section. Instead,
you should use the `templates_file` config option.
This is a slight deviation from the official alertmanager config spec.

#### `templates_file`
Use this option to push templates that are being used by the configuration
file.

All templates need to go into this single config option, instead of
the 'templates' section of the main configuration file. The templates will be
pushed to the workload container, and the configuration file will be updated
accordingly.
Refer to the
[official documentation](https://prometheus.io/docs/alerting/latest/notification_examples/)
for more details on templates.

### Actions
- `show-config`: Show alertmanager config file.

### Scale Out Usage
HA is achieved by providing each Alertmanager instance at least one IP address
of another instance. The cluster would then auto-update with subsequent changes
to the cluster.

You may add additional Alertmanager units for high availability

```shell
juju add-unit alertmanager-k8s
```

Scaling alertmanager would automatically cause karma to group alerts by
cluster.

### Dashboard

The Alertmanager dashboard may be accessed at the default port (9093) on the IP
address of the Alertmanager unit, which is determinable with a `juju status` command.

## Relations

Currently, supported relations are:
  - [Prometheus](https://github.com/canonical/prometheus-operator), which forwards alerts to
    Alertmanager over the `alertmanager_dispatch` interface.
    Set up with `juju add-relation alertmanager-k8s prometheus-k8s`.
  - [Karma](https://github.com/canonical/karma-operator), which displays alerts from all related alertmanager instances
    over the `karma_dashboard` interface.
    Set up with `juju add-relation alertmanager-k8s karma-k8s`.


## OCI Images
This charm can be used with the following images:
- [`ubuntu/prometheus-alertmanager`](https://hub.docker.com/r/ubuntu/prometheus-alertmanager) (default)
- [`quay.io/prometheus/alertmanager`](https://quay.io/repository/prometheus/alertmanager?tab=tags)

### Resource revisions
| Resource           | Revision | Image             |
|--------------------|:--------:|-------------------|
| alertmanager-image | r1       | [0.21-20.04_beta] |

## Additional Information
- [Logging, Monitoring, and Alerting](https://discourse.ubuntu.com/t/logging-monitoring-and-alerting/19151) (LMA) -
  a tutorial for running Prometheus, Grafana and Alertmanager with LXD.
- [Alertmanager README](https://github.com/prometheus/alertmanager)
- [PromCon 2018: Life of an Alert](https://youtube.com/watch?v=PUdjca23Qa4)


[0.21-20.04_beta]: https://hub.docker.com/layers/ubuntu/prometheus-alertmanager/0.21-20.04_beta/images/sha256-1418c677768887c2c717d043c9cb8397a32552a61354cb98c25cef23eeeb2b3f?context=explore

# Alertmanager Operator (k8s)

## Description

The [Alertmanager] operator provides an alerting solution for the [Prometheus][Prometheus Docs] 
[Operator][Prometheus Operator]. It is part of an Observability stack in the [Juju] charm
[ecosystem]. Alertmanager accepts alerts from Prometheus, then deduplicates, groups
and routes them to the selected receiver, based on a set of alerting rules. These
alerting rules may be set by any supported [charm] that uses the services of
Prometheus by forming a relation with it.

[Alertmanager]: https://prometheus.io/docs/alerting/latest/alertmanager/
[Prometheus Docs]: https://prometheus.io/docs/introduction/overview/
[Prometheus Operator]: https://github.com/canonical/prometheus-operator
[Juju]: https://jaas.ai/
[ecosystem]: https://charmhub.io/
[charm]: https://charmhub.io/

## Usage

    juju deploy alertmanager-k8s


### Configuration

Currently, supported receivers are
  - [PagerDuty](https://www.pagerduty.com/) (set up with:
    `juju config alertmanager-k8s pagerduty_key='your-key'`)

### Actions
None.

### Scale Out Usage

You may add additional Alertmanager units for high availability

    juju add-unit alertmanager-k8s

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
This charm can be used with the folowing images:
- [`ubuntu/prometheus-alertmanager`](https://hub.docker.com/r/ubuntu/prometheus-alertmanager) (default)
- [`quay.io/prometheus/alertmanager`](https://quay.io/repository/prometheus/alertmanager?tab=tags)


## Additional Information
- [Logging, Monitoring, and Alerting](https://discourse.ubuntu.com/t/logging-monitoring-and-alerting/19151) (LMA) - 
  a tutorial for running Prometheus, Grafana and Alertmanager with LXD.
- [Alertmanager README](https://github.com/prometheus/alertmanager)
- [PromCon 2018: Life of an Alert](https://youtube.com/watch?v=PUdjca23Qa4)

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

## Deployment

    juju deploy alertmanager-k8s


### Receivers

Currently, supported receivers are
  - [PagerDuty](https://www.pagerduty.com/) (set up with:
    `juju config alertmanager-k8s pagerduty_key='your-key'`)

### Scale Out Usage

You may add additional Alertmanager units for high availability

    juju add-unit alertmanager-k8s

## Provided relations

Currently, supported relations are:
  - [Prometheus](https://github.com/canonical/prometheus-operator) (set up with: 
    `juju add-relation alertmanager-k8s:alerting prometheus-k8s:alertmanager`)

## Developing

Use your existing Python 3 development environment or create and
activate a Python 3 virtualenv

    virtualenv -p python3 venv
    source venv/bin/activate

Install the development requirements

    pip install -r requirements-dev.txt

Later on, upgrade packages as needed

    pip install --upgrade -r requirements-dev.txt

## Roadmap
- Improve tests
- Add additional receivers: webhook, Pushover

## Additional information
- [Logging, Monitoring, and Alerting](https://discourse.ubuntu.com/t/logging-monitoring-and-alerting/19151) (LMA) - 
  a tutorial for running Prometheus, Grafana and Alertmanager with LXD.
- [Alertmanager README](https://github.com/prometheus/alertmanager)
- [PromCon 2018: Life of an Alert](https://youtube.com/watch?v=PUdjca23Qa4)
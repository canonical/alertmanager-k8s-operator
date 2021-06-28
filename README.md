# Alertmanager Operator (k8s)

## Description

The [Alertmanager] handles alerts sent by client applications such as the .[Prometheus server], and it takes care of deduplicating, grouping and routing them to the correct receiver integration such as email, webhooks and SaaS alert management products. It also takes care of silencing and inhibition of alerts.

This Alertmanager operator is designed to interoperate with the [Juju] [Prometheus Operator][Prometheus Operator] and the rest of the [Juju charm ecosystem].

## Usage

```sh
$ juju deploy alertmanager-k8s
```

### Receivers

Currently, supported receivers are

* [PagerDuty](https://www.pagerduty.com/), which you can configure with:

  ```sh
  $ juju config alertmanager-k8s pagerduty_key='your-key'
  ```

### Scale Out Usage

You may add additional Alertmanager units for high availability

```sh
juju add-unit alertmanager-k8s
```

## Relations

Currently, supported relations are:

* [Prometheus], which you can configure set up with:

  ```sh
  $ juju add-relation alertmanager-k8s:alerting prometheus-k8s:alertmanager
  ```

## OCI Images

This charm by default uses the latest version of the [ubuntu/prometheus-alertmanager](https://hub.docker.com/r/ubuntu/prometheus-alertmanager) image.

[Alertmanager]: https://prometheus.io/docs/alerting/latest/alertmanager/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Prometheus Operator]: https://github.com/canonical/prometheus-operator
[Juju]: https://jaas.ai/
[charm ecosystem]: https://charmhub.io/

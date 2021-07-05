# Contributing to alertmanager-k8s
Alertmanager, as the name suggests, filters incoming alerts and routes them to pre-defined 
receivers. Alertmanager reads its configuration from an `alertmanager.yml`, some aspects of which 
are exposed to the user via `juju config` calls (see [`config.yaml`](config.yaml)).
In the future, integrator charms may be used for configuring Alertmanager.

The intended use case of this operator is to be deployed together with the 
[prometheus-k8s operator](https://github.com/canonical/prometheus-operator), although that is not 
necessary, as [Alertmanager's HTTP API][Alertmanager API browser] could be 
[used](https://github.com/prometheus/alertmanager/issues/437#issuecomment-263413632) instead.

HA is achieved by providing each Alertmanager instance at least one IP address of another instance.
The cluster would then auto-update with subsequent changes to the cluster.

## Known issues
1. Adding multiple receivers of the same type (e.g. PagerDuty) is not very scalable, due to the 
   nature of the `juju config` command. This is likely to improve in the future by using integrator
   charms.

## Bugs and pull requests
- Generally, before developing enhancements to this charm, you should consider
  [opening an issue ](https://github.com/canonical/alertmanager-operator) explaining
  your use case.
- If you would like to chat with us about your use-cases or proposed
  implementation, you can reach us at
  [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
- It is strongly recommended that prior to engaging in any enhancements
  to this charm you familiarise your self with Juju.
- Familiarising yourself with the
  [Charmed Operator Framework](https://juju.is/docs/sdk).
  library will help you a lot when working on PRs.
- All enhancements require review before being merged. Besides the
  code quality and test coverage, the review will also take into
  account the resulting user experience for Juju administrators using
  this charm. Please help us out in having easier reviews by rebasing
  onto the `main` branch, avoid merge commits and enjoy a linear Git
  history.


## Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be found in the 
[Juju docs](https://juju.is/docs/olm/microk8s).

## Developing

Use your existing Python 3 development environment or create and
activate a Python 3 virtualenv

    virtualenv -p python3 venv
    source venv/bin/activate

Install the development requirements

    pip install -r requirements-dev.txt

Later on, upgrade packages as needed

    pip install --upgrade -r requirements-dev.txt


### Testing

    ./run_tests

## Build charm

Install the charmcraft tool

    sudo snap install charmcraft

Build the charm in this git repository using

    charmcraft pack

## Usage
First deploy Prometheus following instructions from its
[repository](https://github.com/canonical/prometheus-operator). You
may also deploy Prometheus using [Charmhub](https://charmhub.io/)

Now deploy the Alertmanger charm you just built. Alertmanager may
support mulitple alert receivers (see below). In order to use any of
these receivers relavent configuration information is required at
deployment or subsequently. Without any configured receiver
Alertmanager will enter a blocked state.

### Tested images
- [`ubuntu/prometheus-alertmanager`](https://hub.docker.com/r/ubuntu/prometheus-alertmanager)
- [`quay.io/prometheus/alertmanager`](https://quay.io/repository/prometheus/alertmanager?tab=tags)

### Deploy Alertmanager with PagerDuty configuration

    juju deploy ./alertmanager-k8s.charm \
      --resource alertmanager-image=ubuntu/prometheus-alertmanager \
      --config pagerduty_key='your-key'

Alternatively you may deploy Alertmanger without a pagerduty key to let it enter the
blocked state, and provide a key later on to unblock Alertmanager:

    juju deploy ./alertmanager-k8s.charm \
      --resource alertmanager-image=quay.io/prometheus/alertmanager
    
    # Later on, unblock with:
    # juju config alertmanager-k8s pagerduty_key='your-key'

Finally, add a relation between Prometheus and Alertmanager:

    juju add-relation prometheus-k8s:alertmanager alertmanager-k8s:alerting


## References
- [Alertmanager API browser](https://petstore.swagger.io/?url=https://raw.githubusercontent.com/prometheus/alertmanager/master/api/v2/openapi.yaml)

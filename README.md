# Alertmanager Operator

## Description

The [Alertmanager] operator provides an alerting solution for the
[Prometheus Operator]. It is part of an Observability stack in the [Juju] charm
[ecosystem]. Alertmanager accepts alerts from Prometheus, then deduplicates, groups
and routes them to the selected receiver, based on a set of alerting rules. These
alerting rules may be set by any supported [charm] that uses the services of
Prometheus by forming a relation with it.

[Alertmanager]: https://prometheus.io/docs/alerting/latest/alertmanager/
[Prometheus Operator]: https://github.com/canonical/prometheus-operator
[Juju]: https://jaas.ai/
[ecosystem]: https://charmhub.io/
[charm]: https://charmhub.io/

## Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands

    sudo snap install microk8s --classic
    microk8s.enable dns storage registry dashboard
    sudo snap install juju --classic
    juju bootstrap microk8s microk8s
    juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath

## Build

Install the charmcraft tool

    sudo snap install charmcraft

Build the charm in this git repository using

    charmcraft build

## Usage

Create a Juju model (say "lma") for your observability operators

    juju add-model lma

First deploy Prometheus following instructions from the its
[repository](https://github.com/canonical/prometheus-operator). You
may also deploy Prometheus using [Charmhub](https://charmhub.io/)

Now deploy the Alertmanger charm you just built. Alertmanager may
support mulitple alert receivers (see below). In order to use any of
these receivers relavent configuration information is required at
deployment or subsequently. Without any configured receiver
Alertmanager will enter a blocked state.

Deploy Alertmanager with PagerDuty configuration

    juju deploy ./alertmanager.charm --config pagerduty_key='your-key'


Alternatively you may just deploy Alertmanger and let it enter the
blocked state as in

    juju deploy ./alertmanager.charm

Subsequently you can then specify the receiver configuration as in

    juju config alertmanager pagerduty_key='your-key'

This should unblock Alertmanager.

Finally add a relation between Prometheus and Alertmanager.

    juju add-relation prometheus alertmanager

### Scale Out Usage

You may add additional  Alertmanager units for high availability

    juju add-unit alertmanager

## Relations

   Currently supported relations are
   - [Prometheus](https://github.com/canonical/prometheus-operator)

## Receivers

   Currently supported receivers are
   - [PagerDuty](https://www.pagerduty.com/)

## Developing

Use your existing Python 3 development environment or create and
activate a Python 3 virtualenv

    virtualenv -p python3 venv
    source venv/bin/activate

Install the development requirements

    pip install -r requirements-dev.txt

## Testing

Just run `run_tests`:

    ./run_tests

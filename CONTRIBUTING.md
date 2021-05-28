# Contributing to alertmanager-k8s

## Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands

    sudo snap install microk8s --classic
    microk8s.enable dns storage
    sudo snap install juju --classic
    juju bootstrap microk8s microk8s
    juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath

Create a Juju model (say "lma") for your observability operators

    juju add-model lma

## Build

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

### Deploy Alertmanager with PagerDuty configuration

    juju deploy ./alertmanager-k8s.charm \
      --resource alertmanager-image=quay.io/prometheus/alertmanager \
      --config pagerduty_key='your-key'

Alternatively you may deploy Alertmanger without a pagerduty key to let it enter the
blocked state, and provide a key later on to unblock Alertmanager:

    juju deploy ./alertmanager-k8s.charm \
      --resource alertmanager-image=quay.io/prometheus/alertmanager
    
    # Later on, unblock with:
    # juju config alertmanager-k8s pagerduty_key='your-key'

Finally, add a relation between Prometheus and Alertmanager:

    juju add-relation prometheus-k8s:alertmanager alertmanager-k8s:alerting


# Contributing to alertmanager-k8s
Alertmanager, as the name suggests, filters incoming alerts and routes them to
pre-defined receivers. Alertmanager reads its configuration from an
`alertmanager.yml`, some aspects of which are exposed to the user via
`juju config` calls (see [`config.yaml`](config.yaml)).
In the future, integrator charms may be used for configuring Alertmanager.

The intended use case of this operator is to be deployed together with the
[prometheus-k8s operator][Prometheus operator], although that is not
necessary, as [Alertmanager's HTTP API][Alertmanager API browser] could be
[used](https://github.com/prometheus/alertmanager/issues/437#issuecomment-263413632)
instead.

## Known issues
1. Adding multiple receivers of the same type (e.g. PagerDuty) is not very scalable, due to the
   nature of the `juju config` command. This is likely to improve in the future by using integrator
   charms.

## Bugs and pull requests
- Generally, before developing enhancements to this charm, you should consider
  explaining your use case.
- If you would like to chat with us about your use-cases or proposed
  implementation, you can reach us at
  [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
- All enhancements require review before being merged. Apart from
  code quality and test coverage, the review will also take into
  account the resulting user experience for Juju administrators using
  this charm.

## Setup

A typical setup using [snaps](https://snapcraft.io/) can be found in the
[Juju docs](https://juju.is/docs/sdk/dev-setup).

## Developing

Use your existing Python 3 development environment or create and
activate a Python 3 virtualenv

```shell
virtualenv -p python3 venv
source venv/bin/activate
```

Install the development requirements

```shell
pip install -r requirements.txt
```

Later on, upgrade packages as needed

```shell
pip install --upgrade -r requirements.txt
```

### Testing
```shell
tox -e fmt              # update your code according to linting rules
tox -e lint             # code style
tox -e static           # static analysis
tox -e unit             # unit tests
tox -e integration      # integration tests
tox -e integration-lma  # integration tests for the lma-light bundle
```

tox creates virtual environment for every tox environment defined in
[tox.ini](tox.ini). To activate a tox environment for manual testing,

```shell
source .tox/unit/bin/activate
```

#### Manual testing
Alerts can be created using [`amtool`](https://manpages.debian.org/testing/prometheus-alertmanager/amtool.1.en.html),

```shell
amtool alert add alertname=oops service="my-service" severety=warning \
    instance="oops.example.net" --annotation=summary="High latency is high!" \
    --generator-url="http://prometheus.int.example.net"
```

or using alertmanager's HTTP API,
[for example](https://gist.github.com/cherti/61ec48deaaab7d288c9fcf17e700853a):

```shell
alertmanager_ip=$(juju status alertmanager/0 --format=json | \
  jq -r ".applications.alertmanager.units.\"alertmanager/0\".address")

curl -XPOST http://$alertmanager_ip:9093/api/v1/alerts -d "[{
	\"status\": \"firing\",
	\"labels\": {
		\"alertname\": \"$name\",
		\"service\": \"my-service\",
		\"severity\":\"warning\",
		\"instance\": \"$name.example.net\"
	},
	\"annotations\": {
		\"summary\": \"High latency is high!\"
	},
	\"generatorURL\": \"http://prometheus.int.example.net\"
}]"
```

The alert should then be listed,

```shell
curl http://$alertmanager_ip:9093/api/v1/alerts
```

and visible on a karma dashboard, if configured.

Relations between alertmanager and prometheus can be verified by
[querying prometheus](https://prometheus.io/docs/prometheus/latest/querying/api/#alertmanagers)
for active alertmanagers:

```shell
curl -X GET "http://$prom_ip:9090/api/v1/alertmanagers"
```

## Build charm

Build the charm in this git repository using
```shell
charmcraft pack
```

## Usage
First deploy [Prometheus][Prometheus operator].

Now deploy the Alertmanger charm you just built. Alertmanager may
support multiple alert receivers (see below). In order to use any of
these receivers relevant configuration information is required at
deployment or subsequently. Without any configured receiver
Alertmanager will use a dummy receiver.

### Tested images
For local deployment, this charms was tested with the following images:
- [`ubuntu/prometheus-alertmanager`](https://hub.docker.com/r/ubuntu/prometheus-alertmanager)
- [`quay.io/prometheus/alertmanager`](https://quay.io/repository/prometheus/alertmanager?tab=tags)

### Deploy Alertmanager with custom configuration

```shell
juju deploy ./alertmanager-k8s.charm \
  --resource alertmanager-image=ubuntu/prometheus-alertmanager \
  --config config_file='@path/to/alertmanager.yml' \
  --config templates_file='@path/to/templates.tmpl'
```

Alternatively you may deploy Alertmanger without a config file, in which case
a default configuration with a dummy receiver would be loaded.
A configuration file can be provided later:

```shell
juju deploy ./alertmanager-k8s.charm \
  --resource alertmanager-image=ubuntu/prometheus-alertmanager

# Later on, update configuration with:
juju config alertmanager-k8s config_file='@path/to/alertmanager.yml'  # etc.
```

Finally, add a relation between Prometheus and Alertmanager:

```shell
juju add-relation prometheus-k8s:alertmanager alertmanager-k8s:alerting
```

## Code overview
- The main charm class is `AlertmanagerCharm`, which responds to config changes
  (via `ConfigChangedEvent`) and cluster changes (via `RelationJoinedEvent`,
  `RelationChangedEvent` and `RelationDepartedEvent`).
- All lifecycle events call a common hook, `_common_exit_hook` after executing
  their own business logic. This pattern simplifies state tracking and improves
  consistency.
- On startup, the charm waits for `PebbleReadyEvent` and for an IP address to
  become available before starting the karma service and declaring
  `ActiveStatus`. The charm must be related to an alertmanager instance,
  otherwise the charm will go into blocked state.

## Design choices
- The `alertmanager.yml` config file is created in its entirety by the charm
  code on startup (the default `alertmanager.yml` is overwritten). This is done
  to maintain consistency across OCI images.
- Hot reload via the alertmanager HTTP API is used whenever possible instead of
  service restart, to minimize downtime.

## Roadmap
- Test using pytest-operator
- Use integrator charms


[Alertmanager API browser]: https://petstore.swagger.io/?url=https://raw.githubusercontent.com/prometheus/alertmanager/master/api/v2/openapi.yaml
[gh:Prometheus operator]: https://github.com/canonical/prometheus-operator
[Prometheus operator]: https://charmhub.io/prometheus-k8s

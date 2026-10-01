# Contributing to alertmanager-k8s
![GitHub](https://img.shields.io/github/license/canonical/alertmanager-k8s-operator)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/canonical/alertmanager-k8s-operator)
![GitHub](https://img.shields.io/tokei/lines/github/canonical/alertmanager-k8s-operator)
![GitHub](https://img.shields.io/github/issues/canonical/alertmanager-k8s-operator)
![GitHub](https://img.shields.io/github/issues-pr/canonical/alertmanager-k8s-operator) ![GitHub](https://img.shields.io/github/contributors/canonical/alertmanager-k8s-operator) ![GitHub](https://img.shields.io/github/watchers/canonical/alertmanager-k8s-operator?style=social)

## Overview

This documents explains the processes and practices recommended for
contributing enhancements or bug fixing to the Alertmanager Charmed Operator.

The intended use case of this operator is to be deployed as part of the
[COS Lite] bundle, although that is not necessary.


## Setup

A typical setup using [snaps](https://snapcraft.io/) can be found in the
[Juju docs](https://juju.is/docs/sdk/dev-setup).


## Developing

- Prior to getting started on a pull request, we first encourage you to open an
  issue explaining the use case or bug.
  This gives other contributors a chance to weigh in early in the process.
- To author PRs you should be familiar with [juju](https://juju.is/#what-is-juju)
  and [how operators are written](https://juju.is/docs/sdk).
- The best way to get a head start is to join the conversation on our
  [Mattermost channel] or [Discourse].
- All enhancements require review before being merged. Besides the
  code quality and test coverage, the review will also take into
  account the resulting user experience for Juju administrators using
  this charm. To be able to merge you would have to rebase
  onto the `main` branch. We do this to avoid merge commits and to have a
  linear Git history.
- We use [`tox`](https://tox.wiki/en/latest/#) to manage all virtualenvs for
  the development lifecycle.


### Testing
Unit tests are written with the Operator Framework [test harness] and
integration tests are written using [pytest-operator] and [python-libjuju].

The default test environments - lint, static and unit - will run if you start
`tox` without arguments.

You can also manually run a specific test environment:

```shell
tox -e fmt              # update your code according to linting rules
tox -e lint             # code style
tox -e static           # static analysis
tox -e unit             # unit tests
tox -e integration      # integration tests
tox -e integration-lma  # integration tests for the lma-light bundle
```

`tox` creates a virtual environment for every tox environment defined in
[tox.ini](tox.ini). To activate a tox environment for manual testing,

```shell
source .tox/unit/bin/activate
```


#### Manual testing
Alerts can be created using
[`amtool`](https://manpages.debian.org/testing/prometheus-alertmanager/amtool.1.en.html),

```shell
amtool alert add alertname=oops service="my-service" severity=warning \
    instance="oops.example.net" --annotation=summary="High latency is high!" \
    --generator-url="http://prometheus.int.example.net"
```

or using [Alertmanager's HTTP API][Alertmanager API browser],
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

which will create a `*.charm` file you can deploy with:

```shell
juju deploy ./alertmanager-k8s.charm \
  --resource alertmanager-image=ubuntu/prometheus-alertmanager \
  --config config_file='@path/to/alertmanager.yml' \
  --config templates_file='@path/to/templates.tmpl'
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


[Alertmanager API browser]: https://petstore.swagger.io/?url=https://raw.githubusercontent.com/prometheus/alertmanager/main/api/v2/openapi.yaml
[gh:Prometheus operator]: https://github.com/canonical/prometheus-operator
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[COS Lite]: https://charmhub.io/cos-lite
[Mattermost channel]: https://chat.charmhub.io/charmhub/channels/observability
[Discourse]: https://discourse.charmhub.io/tag/alertmanager
[test harness]: https://ops.readthedocs.io/en/latest/#module-ops.testing
[pytest-operator]: https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md
[python-libjuju]: https://pythonlibjuju.readthedocs.io/en/latest/

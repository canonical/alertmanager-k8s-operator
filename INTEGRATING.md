## Integrating alertmanager-k8s
Alertmanager integrates with any charm that supports the
`alertmanager_dispatch` interface.

### Receivers
By default, when alertmanager starts without user config, a dummy receiver is
generated.

An example deployment with pushover may look as follows:

```shell
# deploy alertmanager, name it "am", and provide pushover credentials
juju deploy alertmanager-k8s am \
  --config pushover::user_key=<your key> --config pushover::token=<your_token>
```

Configuration items are namespaced and key names match exactly the keys
[expected by alertmananger](https://www.prometheus.io/docs/alerting/latest/configuration/#receiver)
in alertmanager.yml.

### Related charms
#### Prometheus
Alertmanager is typically deployed together with
[prometheus][Prometheus operator]:

```shell
juju deploy alertmanager-k8s am
juju deploy prometheus-k8s prom
juju relate am prom
```

which would relate the two charms over the `alertmanager_dispatch` relation
interface.

Scaling alertmanager would automatically update related instances of
prometheus.

#### Karma
[Karma][Karma operator] provides a super slick dashboard for alertmanager.
Check it out with:

```shell
juju deploy alertmanager-k8s am
juju deploy karma-k8s karma
juju relate am karma
```

which would relate the two charms over the `karma_dashboard` relation
interface.

Scaling alertmanager would automatically cause karma to group alerts by
cluster.

#### Karma alertmanager proxy
The [karma alertmanager proxy][Karma alertmanager proxy operator] is intended
for remote alertmanager deployments. This particular use-case is covered by
that charm.


[gh:Prometheus operator]: https://github.com/canonical/prometheus-operator
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[gh:Karma operator]: https://github.com/canonical/karma-operator/
[gh:Karma alertmanager proxy operator]: https://github.com/canonical/karma-alertmanager-proxy-operator
[Karma operator]: https://charmhub.io/karma-k8s/
[Karma alertmanager proxy operator]: https://charmhub.io/karma-alertmanager-proxy-k8s

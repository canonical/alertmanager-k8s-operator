# Changelog

Changes on `track/0.31` since the common ancestor with `origin/track/2` (`c6b653d`).

## Features

- feat(tf): base input variable ([#446](https://github.com/canonical/alertmanager-k8s-operator/pull/446)) (#447)
- feat: loosen AlertmanagerPagerdutyNotificationsFailing  ([#437](https://github.com/canonical/alertmanager-k8s-operator/pull/437))
- feat: add charms blueprint ([#441](https://github.com/canonical/alertmanager-k8s-operator/pull/441))
- feat: add charms blueprint ([#425](https://github.com/canonical/alertmanager-k8s-operator/pull/425))
- feat: bump to 26.04 ([#418](https://github.com/canonical/alertmanager-k8s-operator/pull/418))
- feat(terraform): Support for Juju provider v2 ([#415](https://github.com/canonical/alertmanager-k8s-operator/pull/415))
- feat: add workload tracing ([#414](https://github.com/canonical/alertmanager-k8s-operator/pull/414))
- feat: TF resources variable ([#411](https://github.com/canonical/alertmanager-k8s-operator/pull/411))
- feat: TF service mesh outputs ([#410](https://github.com/canonical/alertmanager-k8s-operator/pull/410))
- feat: add send-logs integration via LogForwarder ([#407](https://github.com/canonical/alertmanager-k8s-operator/pull/407))
- feat: migrate charm-tracing to ops[tracing] ([#408](https://github.com/canonical/alertmanager-k8s-operator/pull/408))
- feat(terraform): add channel validation ([#403](https://github.com/canonical/alertmanager-k8s-operator/pull/403))
- feat: send only one GrafanaSource to grafana ([#379](https://github.com/canonical/alertmanager-k8s-operator/pull/379))
- feat: Change default track to 'dev' in release workflow ([21c54dc](https://github.com/canonical/alertmanager-k8s-operator/commit/21c54dc66bc67682f9076cc8cfd22365561e4086))

## Fixes

- fix: TF channel validation ([#448](https://github.com/canonical/alertmanager-k8s-operator/pull/448))
- fix: constant service restarts ([#440](https://github.com/canonical/alertmanager-k8s-operator/pull/440))
- fix: Split TF endpoints output to requires/provides ([#396](https://github.com/canonical/alertmanager-k8s-operator/pull/396))
- fix: AlertmanagerJobMissing rule ([#381](https://github.com/canonical/alertmanager-k8s-operator/pull/381))
- fix: inclusive naming check ([#382](https://github.com/canonical/alertmanager-k8s-operator/pull/382))

## Others

- chore: refresh charms.just from canonical/observability ([fb59685](https://github.com/canonical/alertmanager-k8s-operator/commit/fb5968514c22c1aac5fdff4ea45ec48a525f5169))
- ci: allow manually calling the release workflow ([cd41dd0](https://github.com/canonical/alertmanager-k8s-operator/commit/cd41dd0154028b68f2e0c48b20c29bb62cdd23e8))
- chore: upgrade grafana_source library to v1 for stable datasource UIDs ([#442](https://github.com/canonical/alertmanager-k8s-operator/pull/442))
- chore: update charm libraries ([#435](https://github.com/canonical/alertmanager-k8s-operator/pull/435))
- chore: update charm libraries ([#433](https://github.com/canonical/alertmanager-k8s-operator/pull/433))
- chore: update charm libraries ([#431](https://github.com/canonical/alertmanager-k8s-operator/pull/431))
- chore: update charm libraries ([#428](https://github.com/canonical/alertmanager-k8s-operator/pull/428))
- chore: update charm libraries ([#427](https://github.com/canonical/alertmanager-k8s-operator/pull/427))
- chore: update charm libraries ([#426](https://github.com/canonical/alertmanager-k8s-operator/pull/426))
- chore: update charm libraries ([#424](https://github.com/canonical/alertmanager-k8s-operator/pull/424))
- chore: update charm libraries ([#422](https://github.com/canonical/alertmanager-k8s-operator/pull/422))
- chore: update charm libraries ([#421](https://github.com/canonical/alertmanager-k8s-operator/pull/421))
- chore: update charm libraries ([#420](https://github.com/canonical/alertmanager-k8s-operator/pull/420))
- chore: update charm libraries ([#419](https://github.com/canonical/alertmanager-k8s-operator/pull/419))
- docs: update documentation link to sphinx ([#417](https://github.com/canonical/alertmanager-k8s-operator/pull/417))
- chore: update charm libraries ([#416](https://github.com/canonical/alertmanager-k8s-operator/pull/416))
- chore(deps): update ubuntu/alertmanager:0.31-24.04 docker digest to ce3060f (main) ([#404](https://github.com/canonical/alertmanager-k8s-operator/pull/404))
- ci: fix token permissions for release workflow ([#413](https://github.com/canonical/alertmanager-k8s-operator/pull/413))
- ci: add explicit workflow permissions for CodeQL ([#412](https://github.com/canonical/alertmanager-k8s-operator/pull/412))
- chore: update charm libraries ([#409](https://github.com/canonical/alertmanager-k8s-operator/pull/409))
- chore(ci): bump reusable workflows to v2 ([#406](https://github.com/canonical/alertmanager-k8s-operator/pull/406))
- docs: improve charmcraft.yaml description field ([#401](https://github.com/canonical/alertmanager-k8s-operator/pull/401))
- chore: extend renovate config to all production branches ([7718d5b](https://github.com/canonical/alertmanager-k8s-operator/commit/7718d5b81dc0ec34ef516b7f03e2ac18a3655b5f))
- chore: update charm libraries ([#400](https://github.com/canonical/alertmanager-k8s-operator/pull/400))
- chore: update charm libraries ([#398](https://github.com/canonical/alertmanager-k8s-operator/pull/398))
- update prometheus_scrape lib ([#397](https://github.com/canonical/alertmanager-k8s-operator/pull/397))
- chore: update charm libraries ([#394](https://github.com/canonical/alertmanager-k8s-operator/pull/394))
- chore: Bumps Alertmanager to 0.31 ([#392](https://github.com/canonical/alertmanager-k8s-operator/pull/392))
- chore: update charm libraries ([#391](https://github.com/canonical/alertmanager-k8s-operator/pull/391))
- chore: update charm libraries ([#390](https://github.com/canonical/alertmanager-k8s-operator/pull/390))
- chore: fix ci ([#389](https://github.com/canonical/alertmanager-k8s-operator/pull/389))
- chore: update charm libraries ([#387](https://github.com/canonical/alertmanager-k8s-operator/pull/387))
- chore: update charm libraries ([#386](https://github.com/canonical/alertmanager-k8s-operator/pull/386))


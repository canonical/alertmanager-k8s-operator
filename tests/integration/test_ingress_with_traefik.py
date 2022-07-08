#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


def test_endpoint_reachable_without_ingress():
    # The following should return '{"status":"success","data":[]}':
    # - from charm container: curl http://am-endpoints.mdl.svc.cluster.local:9093/api/v1/alerts
    # - from charm container: curl localhost:9093/api/v1/alerts
    # - from host (itest): curl 10.1.55.23:9093/api/v1/alerts (i.e. unit IP)
    # TODO
    pass


def test_amtool_able_to_reach_alertmanager():
    # amtool config may need to be updated with ingress/path..?
    pass

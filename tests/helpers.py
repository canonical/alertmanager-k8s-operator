# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerConsumer, AlertmanagerProvider

from ops.charm import CharmBase
from ops.framework import StoredState


class DummyCharmForTestingProvider(CharmBase):
    """A class for mimicking the bare AlertmanagerCharm functionality needed to test the provider.
    """
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.provider = AlertmanagerProvider(self, "alertmanager")

        self._stored.set_default(
            pebble_ready=True,
            config_hash=None,
            launched_with_peers=False,
        )


class DummyCharmForTestingConsumer(CharmBase):
    """A class for mimicking the bare AlertmanagerCharm functionality needed to test the consumer.
    """
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        # Must use "alerting" as the relation name because the harness parses metadata.yaml and
        # that is the relation name there (in prometheus, for example, the relation name is
        # "alertmanager" rather than "alerting").
        self.alertmanager_lib = AlertmanagerConsumer(self,
                                                     relation_name="alerting",
                                                     consumes={'alertmanager': '>0.0.0'})

    def _on_alertmanager_available(self, event):
        pass


def network_get(*args, **kwargs):
    """patch for the not-yet-implemented testing backend needed for
    self.model.get_binding(event.relation).network.bind_address
    """
    return {'bind-addresses': [
        {
            'mac-address': '', 'interface-name': '',
            'addresses': [{'hostname': '', 'value': '10.1.157.116', 'cidr': ''}]
        }
    ], 'egress-subnets': ['10.152.183.65/32'], 'ingress-addresses': ['10.152.183.65']}

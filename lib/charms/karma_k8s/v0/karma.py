# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

""" # Karma library

This library is designed to be used by a charm consuming or providing the karma-dashboard relation.
"""

import logging

import ops.charm
from ops.framework import EventBase, EventSource, ObjectEvents
from ops.charm import RelationJoinedEvent, RelationDepartedEvent
from ops.relation import ConsumerBase, ProviderBase
from ops.framework import StoredState

from typing import List, Dict, Optional, Iterable

# The unique Charmhub library identifier, never change it
LIBID = "abcdef1234"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

logger = logging.getLogger(__name__)


class KarmaAlertmanagerConfig:
    required_fields = ("name", "uri")

    @staticmethod
    def is_valid(config: Dict[str, str]):
        return all(key in config for key in KarmaAlertmanagerConfig.required_fields)


def dict_subset(data: dict, key_subset: Iterable):
    return {k: v for k, v in data.items() if k in key_subset}


class GenericEvent(EventBase):
    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save relation data."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore relation data."""
        self.data = snapshot["data"]


class KarmaAlertmanagerConfigChanged(GenericEvent):
    pass


class KarmaProviderEvents(ObjectEvents):
    alertmanager_config_changed = EventSource(KarmaAlertmanagerConfigChanged)


class KarmaProvider(ProviderBase):
    """A "provider" handler to be used by the Karma charm (the 'provides' side of the 'karma' relation).
    This library offers the interface needed in order to provide Alertmanager URIs and associated information to the
    Karma application.

    To have your charm provide URIs to Karma, declare the interface's use in your charm's metadata.yaml file:

    ```yaml
    provides:
      karma-dashboard:
        interface: karma_dashboard
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_karma.v0.karma import KarmaProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.provider = KarmaProvider(
        self, "karma-dashboard", "karma", "0.0.1"
    )
    ```

    The provider charm is expected to observe and respond to the :class:`KarmaAlertmanagerConfigChanged` event,
    for example:

    ```python
    self.framework.observe(
        self.provider.on.alertmanager_config_changed, self._on_alertmanager_config_changed
    )
    ```

    This provider observes relation joined, changed and departed events on behalf of the charm.

    From charm code you can then obtain the list of proxied alertmanagers via:

    ```python
    alertmanagers = self.provider.get_alertmanager_servers()
    ```

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            service_name (str): service name (must be consistent the consumer)
            version (str): semver-compatible version string

    Attributes:
            charm (CharmBase): consumer charm
    """

    on = KarmaProviderEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name: str, service_name: str, version: str = None):
        super().__init__(charm, relation_name, service_name, version)
        self.charm = charm
        self._relation_name = relation_name
        self._service_name = service_name

        events = self.charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_departed, self._on_relation_departed)
        self._stored.set_default(active_relations=set())

    def get_alertmanager_servers(self) -> List[Dict[str, str]]:
        alertmanager_ips = []
        logger.info("get_alertmanager_servers")

        for relation in self.charm.model.relations[self._relation_name]:
            logger.info("relation.data = %s", relation.data)
            if relation.id not in self._stored.active_relations:
                # relation id is not present in the set of active relations
                # this probably means that RelationBroken did not exit yet (was recently removed)
                continue

            # get data from related application
            data = None
            for key in relation.data:
                if key is not self.charm.unit and isinstance(key, ops.charm.model.Unit):
                    data = relation.data[key]
                    break
            if data:
                config = dict_subset(data, KarmaAlertmanagerConfig.required_fields)
                if KarmaAlertmanagerConfig.is_valid(config) and config not in alertmanager_ips:
                    alertmanager_ips.append(config)
            else:
                logger.warning("no related units in relation dict")

        return alertmanager_ips  # TODO sorted

    def _on_relation_joined(self, event: RelationJoinedEvent):
        self._stored.active_relations.add(event.relation.id)

    def _on_relation_changed(self, _):
        self.on.alertmanager_config_changed.emit()

    def _on_relation_departed(self, event: RelationDepartedEvent):
        self._stored.active_relations -= {event.relation.id}
        self.on.alertmanager_config_changed.emit()

    @property
    def config_valid(self) -> bool:
        # karma will fail starting without alertmanager server(s), which would cause pebble to error out.

        # check that there is at least one alertmanager server configured
        servers = self.get_alertmanager_servers()
        logger.info("config_valid: servers = %s", servers)
        return len(servers) > 0


class KarmaConsumer(ConsumerBase):
    """A "consumer" handler to be used by charms that relate to Karma (the 'requires' side of the 'karma' relation).
    This library offers the interface needed in order to provide Alertmanager URIs and associated information to the
    Karma application.

    To have your charm provide URIs to Karma, declare the interface's use in your charm's metadata.yaml file:

    ```yaml
    requires:
      karma-dashboard:
        interface: karma_dashboard
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_karma.v0.karma import KarmaConsumer
    ```

    In your charm's `__init__` method:

    ```python
    self.karma_lib = KarmaConsumer(
        self,
        "karma-dashboard",
        consumes={"karma": ">=0.0.1"},
    )
    ```

    The consumer charm is expected to set config via the consumer library, for example in config-changed:

        if not self.karma_lib.set_config(config):
            logger.warning("Invalid config: %s", config)

    The consumer charm can then obtain the configured IP address, for example:

        self.unit.status = ActiveStatus("Proxying {}".format(self.karma_lib.ip_address))

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """

    _stored = StoredState()

    def __init__(self, charm, relation_name: str, consumes: dict, multi: bool = False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self._consumer_relation_name = relation_name  # from consumer's metadata.yaml
        self._stored.set_default(config={})

        events = self.charm.on[self._consumer_relation_name]

        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent):
        if not self.model.unit.is_leader():
            return

        # update app data bag
        event.relation.data[self.charm.unit].update(self._stored.config)

    @property
    def config_valid(self):
        return KarmaAlertmanagerConfig.is_valid(self._stored.config)

    @property
    def ip_address(self) -> Optional[str]:
        return self._stored.config.get("uri", None)

    def set_config(self, name: str, uri: str) -> bool:
        config = {"name": name, "uri": uri}
        if not KarmaAlertmanagerConfig.is_valid(config):
            logger.warning("Invalid config: {%s, %s}", name, uri)
            return False

        self._stored.config.update(config)
        logger.info("stored config: %s", self._stored.config)

        if self.model.unit.is_leader() and self._consumer_relation_name in self.charm.model.relations:
            for relation in self.charm.model.relations[self._consumer_relation_name]:
                relation.data[self.charm.unit].update(self._stored.config)

        return True

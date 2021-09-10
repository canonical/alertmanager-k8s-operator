#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Karma library.

This library is designed to be used by a charm consuming or providing the karma-dashboard relation.
"""

import logging
from typing import Dict, List, Optional

import ops.charm
from ops.charm import CharmBase, RelationJoinedEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState

# The unique Charmhub library identifier, never change it
LIBID = "abcdef1234"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

logger = logging.getLogger(__name__)


class KarmaAlertmanagerConfig:
    """A helper class for alertmanager server configuration for Karma.

    Refer to the Karma documentation for full details:
    https://github.com/prymitive/karma/blob/main/docs/CONFIGURATION.md#alertmanagers
    """

    required_fields = {"name", "uri"}
    optional_fields = {"cluster"}
    _supported_fields = required_fields | optional_fields

    @staticmethod
    def is_valid(config: Dict[str, str]) -> bool:
        """Validate alertmanager server configuration for Karma.

        Args:
            config: target configuration to be validated.

        Returns:
            True if all required keys are present and all remaining keys are supported optional
            fields; False otherwise.
        """
        all_required = all(key in config for key in KarmaAlertmanagerConfig.required_fields)
        all_supported = all(key in KarmaAlertmanagerConfig._supported_fields for key in config)
        return all_required and all_supported

    @staticmethod
    def from_dict(data: Dict[str, str]) -> Dict[str, str]:
        """Generate alertmanager server configuration from the given dict.

        Configuration is constructed by creating a subset of the provided dictionary that contains
        only the supported fields.

        Args:
            data: a dict that may contain alertmanager server configuration for Karma.

        Returns:
            A subset of `data` that contains all the supported fields found in `data`, if the
            resulting subset makes a valid configuration; False otherwise.
        """
        config = {k: data[k] for k in data if k in KarmaAlertmanagerConfig.required_fields}
        optional_config = {
            k: data[k] for k in data if data[k] and k in KarmaAlertmanagerConfig.optional_fields
        }
        config.update(optional_config)
        return config if KarmaAlertmanagerConfig.is_valid(config) else {}

    @staticmethod
    def build(name: str, url: str, *, cluster=None) -> Dict[str, str]:
        """Build alertmanager server configuration for Karma.

        Args:
            name: name for the alertmanager unit.
            url: url of the alertmanager api server (including scheme and port)
            cluster: name of a cluster to which the alertmanager unit belongs to (optional)

        Returns:
            Alertmanager server configuration for Karma.
        """
        return KarmaAlertmanagerConfig.from_dict({"name": name, "uri": url, "cluster": cluster})


class KarmaAlertmanagerConfigChanged(EventBase):
    """Event raised when karma configuration is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`KarmaAlertmanagerConfigChanged` should be emitted.
    """

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save relation data."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore relation data."""
        self.data = snapshot["data"]


class KarmaConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `AlertmanagerConsumer`."""

    alertmanager_config_changed = EventSource(KarmaAlertmanagerConfigChanged)


class RelationManagerBase(Object):
    """TODO.

    Attributes:
        name (str): consumer's relation name
    """

    def __init__(self, charm: CharmBase, relation_name):
        super().__init__(charm, relation_name)
        self.name = relation_name


class KarmaConsumer(RelationManagerBase):
    """A "consumer" handler to be used by the Karma charm (the 'requires' side).

    This library offers the interface needed in order to forward Alertmanager URLs and associated
    information to the Karma application.

    To have your charm provide URLs to Karma, declare the interface's use in your charm's
    metadata.yaml file:

    ```yaml
    provides:
      karma-dashboard:
        interface: karma_dashboard
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_karma.v0.karma import KarmaConsumer
    ```

    In your charm's `__init__` method:

    ```python
    self.karma_consumer = KarmaConsumer(self, "dashboard")
    ```

    The consumer charm is expected to observe and respond to the
    :class:`KarmaAlertmanagerConfigChanged` event, for example:

    ```python
    self.framework.observe(
        self.karma_consumer.on.alertmanager_config_changed, self._on_alertmanager_config_changed
    )
    ```

    This consumer observes relation joined, changed and departed events on behalf of the charm.

    From charm code you can then obtain the list of proxied alertmanagers via:

    ```python
    alertmanagers = self.karma_consumer.get_alertmanager_servers()
    ```

    Arguments:
            charm (CharmBase): consumer charm
            name (str): from consumer's metadata.yaml

    Attributes:
            charm (CharmBase): consumer charm
    """

    on = KarmaConsumerEvents()

    def __init__(self, charm, name: str):
        super().__init__(charm, name)
        self.charm = charm

        events = self.charm.on[self.name]
        self.charm.framework.observe(events.relation_changed, self._on_relation_changed)
        self.charm.framework.observe(events.relation_departed, self._on_relation_departed)

    def get_alertmanager_servers(self) -> List[Dict[str, str]]:
        """Return configuration data for all related alertmanager servers.

        The exact spec is described in the Karma project documentation
        https://github.com/prymitive/karma/blob/main/docs/CONFIGURATION.md#alertmanagers
        Every item in the returned list represents an item under the "servers" yaml section.

        Returns:
            List of server configurations, in the format prescribed by the Karma project
        """
        servers = []

        logger.debug("relations for %s: %s", self.name, self.charm.model.relations[self.name])
        for relation in self.charm.model.relations[self.name]:
            # get data from related application
            for key in relation.data:
                if key is not self.charm.unit and isinstance(key, ops.charm.model.Unit):
                    data = relation.data[key]
                    config = KarmaAlertmanagerConfig.from_dict(data)
                    if config and config not in servers:
                        servers.append(config)

        return servers  # TODO sorted

    def _on_relation_changed(self, _):
        """Event handler for RelationChangedEvent."""
        self.on.alertmanager_config_changed.emit()

    def _on_relation_departed(self, _):
        """Hook is called when a unit leaves, but another unit may still be present."""
        # At this point the unit data bag of the departing unit is gone from relation data
        self.on.alertmanager_config_changed.emit()

    @property
    def config_valid(self) -> bool:
        """Check if the current configuration is valid.

        Returns:
            True if the currently stored configuration for an alertmanager target is valid; False
            otherwise.
        """
        # karma will fail starting without alertmanager server(s), which would cause pebble to
        # error out.

        # check that there is at least one alertmanager server configured
        servers = self.get_alertmanager_servers()
        return len(servers) > 0


class KarmaProvider(RelationManagerBase):
    """A "provider" handler to be used by charms that relate to Karma (the 'provides' side).

    This library offers the interface needed in order to provide Alertmanager URLs and associated
    information to the Karma application.

    To have your charm provide URLs to Karma, declare the interface's use in your charm's
    metadata.yaml file:

    ```yaml
    provides:
      karma-dashboard:
        interface: karma_dashboard
    ```

    A typical example of importing this library might be

    ```python
    from charms.karma_k8s.v0.karma import KarmaProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.karma_provider = KarmaProvider(
        self,
        "karma-dashboard",
        "karma",
    )
    ```

    The provider charm is expected to set the target URL via the consumer library, for example in
    config-changed:

        self.karma_provider.target = "http://whatever:9093"

    The provider charm can then obtain the configured IP address, for example:

        self.unit.status = ActiveStatus("Proxying {}".format(self.karma_provider.target))

    Arguments:
            charm (CharmBase): consumer charm
            name (str): relation name from consumer's metadata.yaml

    Attributes:
            charm (CharmBase): consumer charm
    """

    _stored = StoredState()

    def __init__(self, charm, name: str):
        super().__init__(charm, name)
        self.charm = charm

        # StoredState is used for holding the target URL.
        # It is needed here because the target URL may be set by the consumer before any
        # "karma-dashboard" relation is joined, in which case there are no relation unit data bags
        # available for storing the target URL.
        self._stored.set_default(config={})

        events = self.charm.on[self.name]
        self.charm.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent):
        self._update_relation_data(event)

    @property
    def config_valid(self) -> bool:
        """Check if the current configuration is valid.

        Returns:
            True if the currently stored configuration for an alertmanager target is valid; False
            otherwise.
        """
        return KarmaAlertmanagerConfig.is_valid(self._stored.config)

    @property
    def target(self) -> Optional[str]:
        """str: Alertmanager URL to be used by Karma."""
        return self._stored.config.get("uri", None)

    @target.setter
    def target(self, url: str) -> None:
        """Configure an alertmanager target server to be used by Karma.

        Apart from the server's URL, the server configuration is determined from the juju topology.

        Args:
            url: Complete URL (scheme and port) of the target alertmanager server.

        Returns:
            None.
        """
        name = self.charm.unit.name
        cluster = f"{self.charm.model.name}_{self.charm.app.name}"
        if not (config := KarmaAlertmanagerConfig.build(name, url, cluster=cluster)):
            logger.warning("Invalid config: {%s, %s}", name, url)
            return

        self._stored.config.update(config)

        # target changed - must update all relation data
        self._update_relation_data()

    def _update_relation_data(self, event: RelationJoinedEvent = None):
        """Helper function for updating relation data bags.

        This function can be used in two different ways:
        - update relation data bag of a given event (e.g. a newly joined relation);
        - update relation data for all relations

        Args:
            event: The event whose data bag needs to be updated. If it is None, update data bags of
            all relations.
        """
        if event is None:
            # update all existing relation data
            # a single consumer charm's unit may be related to multiple karma dashboards
            if self.name in self.charm.model.relations:
                for relation in self.charm.model.relations[self.name]:
                    relation.data[self.charm.unit].update(self._stored.config)
        else:
            # update relation data only for the newly joined relation
            event.relation.data[self.charm.unit].update(self._stored.config)

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Karma library.

This library is designed to be used by a charm consuming or providing the karma-dashboard relation.
This library is published as part of the [Karma charm](https://charmhub.io/karma-k8s).

You can file bugs [here](https://github.com/canonical/karma-operator/issues)!

A typical example of including this library might be:

```python
# ...
from charms.karma_k8s.v0.karma_dashboard import KarmaConsumer

class SomeApplication(CharmBase):
  def __init__(self, *args):
    # ...
    self.karma_consumer = KarmaConsumer(self, "dashboard")
    # ...
```
"""

import logging
from typing import Any, Dict, List, Optional

import ops.charm
from ops.charm import CharmBase, RelationJoinedEvent, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState
from pydantic import BaseModel, ValidationError

# The unique Charmhub library identifier, never change it
LIBID = "98f9dc00f7ff4b1197895886bdd92037"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 9

PYDEPS = ["pydantic < 2"]

# Set to match metadata.yaml
INTERFACE_NAME = "karma_dashboard"

logger = logging.getLogger(__name__)


class _KarmaDashboardProviderUnitDataV0(BaseModel):
    name: str
    uri: str
    cluster: str = ""
    proxy: bool = True

    class Config:
        json_encoders = {
            # We need this because relation data values must be strings, not <class 'bool'>
            # Note: In pydantic>=2, can use `field_serializer`.
            bool: lambda v: "true" if v else "false"
        }


class KarmaAlertmanagerConfigChanged(EventBase):
    """Event raised when karma configuration is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`KarmaAlertmanagerConfigChanged` should be emitted.
    """


class KarmaConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `AlertmanagerConsumer`."""

    alertmanager_config_changed = EventSource(KarmaAlertmanagerConfigChanged)


class RelationManagerBase(Object):
    """Base class that represents relation ends ("provides" and "requires").

    :class:`RelationManagerBase` is used to create a relation manager. This is done by inheriting
    from :class:`RelationManagerBase` and customising the sub class as required.

    Attributes:
        name (str): consumer's relation name
    """

    def __init__(self, charm: CharmBase, relation_name, relation_role: RelationRole):
        super().__init__(charm, relation_name)
        self.charm = charm
        self._validate_relation(relation_name, relation_role)
        self.name = relation_name

    def _validate_relation(self, relation_name: str, relation_role: RelationRole):
        try:
            if self.charm.meta.relations[relation_name].role != relation_role:
                raise ValueError(
                    "Relation '{}' in the charm's metadata.yaml must be '{}' "
                    "to be managed by this library, but instead it is '{}'".format(
                        relation_name,
                        relation_role,
                        self.charm.meta.relations[relation_name].role,
                    )
                )
            if self.charm.meta.relations[relation_name].interface_name != INTERFACE_NAME:
                raise ValueError(
                    "Relation '{}' in the charm's metadata.yaml must use the '{}' interface "
                    "to be managed by this library, but instead it is '{}'".format(
                        relation_name,
                        INTERFACE_NAME,
                        self.charm.meta.relations[relation_name].interface_name,
                    )
                )
        except KeyError:
            raise ValueError(
                "Relation '{}' is not in the charm's metadata.yaml".format(relation_name)
            )


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
    from charms.alertmanager_karma.v0.karma_dashboard import KarmaConsumer
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
            relation_charm (CharmBase): consumer charm
    """

    on = KarmaConsumerEvents()  # pyright: ignore

    def __init__(self, charm, relation_name: str = "karma-dashboard"):
        super().__init__(charm, relation_name, RelationRole.requires)
        self.charm = charm

        events = self.charm.on[self.name]
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_departed, self._on_relation_departed)

    def get_alertmanager_servers(self) -> List[Dict[str, Any]]:
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
                if (
                    key is not self.charm.unit
                    and isinstance(key, ops.charm.model.Unit)  # pyright: ignore
                    and relation.data[key]
                ):
                    try:
                        data = _KarmaDashboardProviderUnitDataV0(**relation.data[key])
                    except ValidationError:
                        logger.warning(
                            "Relation data is invalid or not ready; "
                            "contents of relation.data[%s]: %s",
                            key,
                            relation.data[key],
                        )
                    else:
                        # Now convert relation data into config file format. Luckily it's trivial.
                        config = data.dict()
                        if config and config not in servers:
                            servers.append(config)

        return sorted(servers, key=lambda itm: itm["name"])

    def _on_relation_changed(self, _):
        """Event handler for RelationChangedEvent."""
        self.on.alertmanager_config_changed.emit()  # pyright: ignore

    def _on_relation_departed(self, _):
        """Hook is called when a unit leaves, but another unit may still be present."""
        # At this point the unit data bag of the departing unit is gone from relation data
        self.on.alertmanager_config_changed.emit()  # pyright: ignore

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
    from charms.karma_k8s.v0.karma_dashboard import KarmaProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.karma_provider = KarmaProvider(self, "karma-dashboard")
    ```

    The provider charm is expected to set the target URL via the consumer library, for example in
    config-changed:

        self.karma_provider.target = "http://whatever:9093"

    The provider charm can then obtain the configured IP address, for example:

        self.unit.status = ActiveStatus("Proxying {}".format(self.karma_provider.target))

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): relation name from consumer's metadata.yaml

    Attributes:
            charm (CharmBase): consumer charm
    """

    _stored = StoredState()

    def __init__(self, charm, relation_name: str = "dashboard"):
        super().__init__(charm, relation_name, RelationRole.provides)
        self.charm = charm

        # StoredState is used for holding the target URL.
        # It is needed here because the target URL may be set by the consumer before any
        # "karma-dashboard" relation is joined, in which case there are no relation unit data bags
        # available for storing the target URL.
        self._stored.set_default(config={})

        events = self.charm.on[self.name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent):
        self._update_relation_data(event)

    @property
    def target(self) -> Optional[str]:
        """str: Alertmanager URL to be used by Karma."""
        return self._stored.config.get("uri", None)  # type: ignore

    @target.setter
    def target(self, url: str) -> None:
        """Configure an alertmanager target server to be used by Karma.

        Apart from the server's URL, the server configuration is determined from the juju topology.

        Args:
            url: Complete URL (scheme and port) of the target alertmanager server.

        Returns:
            None.
        """
        data = _KarmaDashboardProviderUnitDataV0(
            name=self.charm.unit.name,
            uri=url,
            cluster=f"{self.charm.model.name}_{self.charm.app.name}",
            proxy=True,
        )
        # TODO Use `data.model_dump()` when we switch to pydantic 2
        as_dict = data.dict()
        # Replace bool with str, otherwise:
        # ops.model.RelationDataTypeError: relation data values must be strings, not <class 'bool'>
        as_dict["proxy"] = "true" if as_dict["proxy"] else "false"
        self._stored.config.update(as_dict)  # type: ignore

        # target changed - must update all relation data
        self._update_relation_data()

    def _update_relation_data(self, event: Optional[RelationJoinedEvent] = None):
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
                    relation.data[self.charm.unit].update(self._stored.config)  # type: ignore
        else:
            # update relation data only for the newly joined relation
            event.relation.data[self.charm.unit].update(self._stored.config)  # type: ignore

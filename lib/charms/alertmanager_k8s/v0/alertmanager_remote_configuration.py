# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Alertmanager Remote Configuration library.

This library offers the option of configuring Alertmanager via relation data.
It has been created with the `alertmanager-k8s` and the `alertmanager-k8s-configurer`
(https://charmhub.io/alertmanager-configurer-k8s) charms in mind, but can be used by any charms
which require functionalities implemented by this library.

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.alertmanager_k8s.v0.alertmanager_remote_configuration
```

Charms that need to push Alertmanager configuration to a charm exposing relation using
the `alertmanager_remote_configuration` interface, should use the `RemoteConfigurationProvider`.
Charms that need to can utilize the Alertmanager configuration provided from the external source
through a relation using the `alertmanager_remote_configuration` interface, should use
the `RemoteConfigurationRequirer`.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

import yaml
from ops.charm import CharmBase, RelationJoinedEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "something dummy for now"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "remote-configuration"


class ConfigReadError(Exception):
    """Raised if Alertmanager configuration can't be read."""

    def __init__(self, config_file: Path):
        self.message = "Failed to read {}".format(config_file)

        super().__init__(self.message)


def config_main_keys_are_valid(config: dict) -> bool:
    """Checks whether main keys in the Alertmanager's config file are valid.

    This method facilitates the basic sanity check of Alertmanager's configuration. It checks
    whether given configuration contains only allowed main keys or not. `templates` have been
    removed from the list of allowed main keys to reflect the fact that `alertmanager-k8s` doesn't
    accept it as part of config (see `alertmanager-k8s` description for more details).
    Full validation of the config is done on the `alertmanager-k8s` charm side.

    Args:
        config: Alertmanager config dictionary

    Returns:
        bool: True/False
    """
    allowed_main_keys = [
        "global",
        "receivers",
        "route",
        "inhibit_rules",
        "time_intervals",
        "mute_time_intervals",
    ]
    return all(item in allowed_main_keys for item in config.keys()) if config else False


class AlertmanagerRemoteConfigurationChangedEvent(EventBase):
    """Event emitted when Alertmanager remote_configuration relation data bag changes."""

    pass


class AlertmanagerRemoteConfigurationRequirerEvents(ObjectEvents):
    """Event descriptor for events raised by `AlertmanagerRemoteConfigurationRequirer`."""

    remote_configuration_changed = EventSource(AlertmanagerRemoteConfigurationChangedEvent)


class RemoteConfigurationRequirer(Object):
    """API that manages a required `alertmanager_remote_configuration` relation.

    The `RemoteConfigurationRequirer` object can be instantiated as follows in your charm:

    ```
    from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import (
        RemoteConfigurationRequirer,
    )

    def __init__(self, *args):
        ...
        self.remote_configuration = RemoteConfigurationRequirer(self)
        ...
    ```

    The `RemoteConfigurationRequirer` assumes that, in the `metadata.yaml` of your charm,
    you declare a required relation as follows:

    ```
    requires:
        remote-configuration:  # Relation name
            interface: alertmanager_remote_configuration  # Relation interface
            limit: 1
    ```

    The `RemoteConfigurationRequirer` provides a public `config` method for exposing the data
    from the relation data bag. Typical usage of these methods in the provider charm would look
    something like:

    ```
    def get_config(self, *args):
        ...
        configuration, templates = self.remote_configuration.config()
        ...
        self.container.push("/alertmanager/config/file.yml", configuration)
        self.container.push("/alertmanager/templates/file.tmpl", templates)
        ...
    ```

    Separation of the main configuration and the templates is dictated by the assumption that
    the default provider of the `alertmanager_remote_configuration` relation will be
    `alertmanager-k8s` charm, which requires such separation.
    """

    on = AlertmanagerRemoteConfigurationRequirerEvents()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """API that manages a required `remote-configuration` relation.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: Name of the relation with the `alertmanager_remote_configuration`
                interface as defined in metadata.yaml. Defaults to `remote-configuration`.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        on_relation = self._charm.on[self._relation_name]

        self.framework.observe(on_relation.relation_created, self._on_relation_created)
        self.framework.observe(on_relation.relation_changed, self._on_relation_changed)
        self.framework.observe(on_relation.relation_broken, self._on_relation_broken)

    def _on_relation_created(self, _) -> None:
        """Event handler for remote configuration relation created event.

        Informs about the fact that the configuration from remote provider will be used.
        """
        logger.debug("Using remote configuration from the remote_configuration relation.")

    def _on_relation_changed(self, _) -> None:
        """Event handler for remote configuration relation changed event.

        Emits custom `remote_configuration_changed` event every time remote configuration
        changes.
        """
        self.on.remote_configuration_changed.emit()

    def _on_relation_broken(self, _) -> None:
        """Event handler for remote configuration relation broken event.

        Informs about the fact that the configuration from remote provider will no longer be used.
        """
        logger.debug("Remote configuration no longer available.")

    def config(self) -> Tuple[Optional[dict], Optional[list]]:
        """Exposes Alertmanager configuration sent inside the relation data bag.

        Charm which requires Alertmanager configuration, can access it like below:

        ```
        def get_config(self, *args):
            ...
            configuration, templates = self.remote_configuration.config()
            ...
            self.container.push("/alertmanager/config/file.yml", configuration)
            self.container.push("/alertmanager/templates/file.tmpl", templates)
            ...
        ```

        Returns:
            tuple: Alertmanager configuration (dict) and templates (list)
        """
        return self._alertmanager_config, self._alertmanager_templates

    @property
    def _alertmanager_config(self) -> Optional[dict]:
        """Returns Alertmanager configuration sent inside the relation data bag.

        If the `alertmanager-remote-configuration` relation exists, takes the Alertmanager
        configuration provided in the relation data bag and returns it in a form of a dictionary
        if configuration passes the validation against the Alertmanager config schema.
        If configuration fails the validation, error is logged and config is rejected (empty config
        is returned).

        Returns:
            dict: Alertmanager configuration dictionary
        """
        remote_configuration_relation = self._charm.model.get_relation(self._relation_name)
        if remote_configuration_relation and remote_configuration_relation.app:
            try:
                config_raw = remote_configuration_relation.data[remote_configuration_relation.app][
                    "alertmanager_config"
                ]
                config = yaml.safe_load(config_raw)
                if config_main_keys_are_valid(config):
                    return config
            except KeyError:
                logger.warning(
                    "Remote config provider relation exists, but no config has been provided."
                )
        return None

    @property
    def _alertmanager_templates(self) -> Optional[list]:
        """Returns Alertmanager templates sent inside the relation data bag.

        If the `alertmanager-remote-configuration` relation exists and the relation data bag
        contains Alertmanager templates, returns the templates in the form of a list.

        Returns:
            list: Alertmanager templates
        """
        templates = None
        remote_configuration_relation = self._charm.model.get_relation(self._relation_name)
        if remote_configuration_relation and remote_configuration_relation.app:
            try:
                templates_raw = remote_configuration_relation.data[
                    remote_configuration_relation.app
                ]["alertmanager_templates"]
                templates = json.loads(templates_raw)
            except KeyError:
                logger.warning(
                    "Remote config provider relation exists, but no templates have been provided."
                )
        return templates


class RemoteConfigurationProvider(Object):
    """API that manages a provided `alertmanager_remote_configuration` relation.

    The `RemoteConfigurationProvider` is intended to be used by charms that need to push data
    to other charms over the `alertmanager_remote_configuration` interface.

    The `RemoteConfigurationProvider` object can be instantiated as follows in your charm:

    ```
    from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import
        RemoteConfigurationProvider,
    )

    def __init__(self, *args):
        ...
        config = RemoteConfigurationProvider.load_config_file(FILE_PATH)
        self.remote_configuration_provider = RemoteConfigurationProvider(
            charm=self,
            alertmanager_config=config,
        )
        ...
    ```

    Alternatively, RemoteConfigurationProvider can be instantiated using a factory, which allows
    using a configuration file path directly instead of a configuration string:

    ```
    from charms.alertmanager_k8s.v0.alertmanager_remote_configuration import
        RemoteConfigurationProvider,
    )

    def __init__(self, *args):
        ...
        self.remote_configuration_provider = RemoteConfigurationProvider.with_config_file(
            charm=self,
            config_file=FILE_PATH,
        )
        ...
    ```

    The `RemoteConfigurationProvider` assumes that, in the `metadata.yaml` of your charm,
    you declare a required relation as follows:

    ```
    provides:
        remote-configuration:  # Relation name
            interface: alertmanager_remote_configuration  # Relation interface
    ```

    The `RemoteConfigurationProvider` provides handling of the most relevant charm
    lifecycle events. On each of the defined Juju events, Alertmanager configuration and templates
    from a specified file will be pushed to the relation data bag.
    Inside the relation data bag, Alertmanager configuration will be stored under
    `alertmanager_configuration` key, while the templates under the `alertmanager_templates` key.
    Separation of the main configuration and the templates is dictated by the assumption that
    the default provider of the `alertmanager_remote_configuration` relation will be
    `alertmanager-k8s` charm, which requires such separation.
    """

    def __init__(
        self,
        charm: CharmBase,
        alertmanager_config: Optional[dict] = None,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """API that manages a provided `remote-configuration` relation.

        Args:
            charm: The charm object that instantiated this class.
            alertmanager_config: Alertmanager configuration dictionary.
            relation_name: Name of the relation with the `alertmanager_remote_configuration`
                interface as defined in metadata.yaml. Defaults to `remote-configuration`.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self.alertmanager_config = alertmanager_config
        self._relation_name = relation_name

        on_relation = self._charm.on[self._relation_name]

        self.framework.observe(on_relation.relation_joined, self._on_relation_joined)

    @classmethod
    def with_config_file(
        cls,
        charm: CharmBase,
        config_file: Path,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """The RemoteConfigurationProvider object factory.

        This factory provides an alternative way of instantiating the RemoteConfigurationProvider.
        While the default constructor requires passing a config dict, the factory allows using
        a configuration file path.

        Args:
            charm: The charm object that instantiated this class.
            config_file: Path to the Alertmanager configuration file.
            relation_name: Name of the relation with the `alertmanager_remote_configuration`
                interface as defined in metadata.yaml. Defaults to `remote-configuration`.

        Returns:
            RemoteConfigurationProvider object
        """
        return cls(charm, cls.load_config_file(config_file), relation_name)

    def _on_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Event handler for RelationJoinedEvent.

        Takes care of pushing Alertmanager configuration to the relation data bag.

        Args:
            event: Juju event
        """
        if not self._charm.unit.is_leader():
            return
        if self.alertmanager_config:
            self.update_relation_data_bag(self.alertmanager_config, event.relation)
        else:
            logger.warning("Alertmanager configuration not available. Ignoring...")

    @staticmethod
    def load_config_file(path: Path) -> dict:
        """Reads given Alertmanager configuration file and turns it into a dictionary.

        Args:
            path: Path to the Alertmanager configuration file

        Returns:
            dict: Alertmanager configuration file in a form of a dictionary

        Raises:
            ConfigReadError: if a problem with reading given config file happens
        """
        try:
            with open(path, "r") as config_yaml:
                config = yaml.safe_load(config_yaml)
            return config
        except (FileNotFoundError, OSError, yaml.YAMLError) as e:
            raise ConfigReadError(path) from e

    def update_relation_data_bag(
        self, alertmanager_config: dict, relation: Optional[Relation]
    ) -> None:
        """Updates relation data bag with Alertmanager config and templates.

        Before updating relation data bag, basic sanity check of given configuration is done.

        Args:
            alertmanager_config: Alertmanager configuration dictionary.
            relation: Juju Relation object
        """
        config = alertmanager_config
        templates = self._get_templates(config)
        if config_main_keys_are_valid(config):
            relation.data[self._charm.app]["alertmanager_config"] = json.dumps(config)  # type: ignore[union-attr]  # noqa: E501
            relation.data[self._charm.app]["alertmanager_templates"] = json.dumps(templates)  # type: ignore[union-attr]  # noqa: E501

    def _get_templates(self, config: dict) -> Optional[list]:
        """Prepares templates data to be put in a relation data bag.

        If the main config file contains templates section, content of the files specified in this
        section will be concatenated. At the same time, templates section will be removed from
        the main config, as alertmanager-k8s-operator charm doesn't tolerate it.

        Args:
            config: Alertmanager config

        Returns:
            list: List of templates
        """
        templates = []
        if config and config.get("templates", []):
            for file in config.pop("templates"):
                try:
                    templates.append(self._load_templates_file(file))
                except FileNotFoundError:
                    continue
        return templates

    @staticmethod
    def _load_templates_file(path: Path) -> str:
        """Reads given Alertmanager templates file and returns its content in a form of a string.

        Args:
            path: Alertmanager templates file path

        Returns:
            str: Alertmanager templates

        Raises:
            ConfigReadError: if a problem with reading given config file happens
        """
        try:
            with open(path, "r") as template_file:
                templates = template_file.read()
            return templates
        except (FileNotFoundError, OSError, ValueError) as e:
            raise ConfigReadError(path) from e

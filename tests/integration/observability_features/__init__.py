"""Shared Gherkin features and step definitions for Observability charms.

Synced from canonical/observability (blueprints/charms) by `just refresh`: do not edit here.

A charm test suite opts in by:

1. registering the step modules it needs in its top-level ``conftest.py``::

       pytest_plugins = ["observability_features.steps.tls"]

2. providing a ``charm_under_test`` fixture returning a :class:`CharmUnderTest`, and a ``juju``
   fixture (e.g. from ``pytest-jubilant``);

3. loading the shipped scenarios from a test module::

       from observability_features import feature
       from pytest_bdd import scenarios

       scenarios(feature("tls.feature"))
"""

from importlib.resources import files

from observability_features.charm import CharmUnderTest

__all__ = ["CharmUnderTest", "feature"]


def feature(name: str) -> str:
    """Return the absolute path of a shipped feature file, for ``pytest_bdd.scenarios()``.

    pytest-bdd resolves relative feature paths against the calling module (or
    ``bdd_features_base_dir``), neither of which can point into an installed package; an
    absolute path sidesteps both.
    """
    path = files(__name__) / "features" / name
    if not path.is_file():
        raise FileNotFoundError(f"no shared feature file named {name!r}")
    return str(path)

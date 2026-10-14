"""The contract between the shared steps and the charm under test."""

from dataclasses import dataclass, field

import jubilant


@dataclass(frozen=True)
class CharmUnderTest:
    """What the shared steps need to know about the charm under test.

    Charm test suites expose an instance through a ``charm_under_test`` fixture.
    """

    app: str
    """Juju application name to deploy the charm as."""
    charm: str
    """Local ``.charm`` path or Charmhub name."""
    workload_port: int
    """Port the workload serves its API on."""
    resources: dict[str, str] = field(default_factory=dict)
    trust: bool = True

    def deploy(self, juju: jubilant.Juju) -> None:
        juju.deploy(self.charm, self.app, resources=self.resources, trust=self.trust)

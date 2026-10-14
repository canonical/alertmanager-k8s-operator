"""Idempotent Juju operations shared by the step modules.

pytest-jubilant scopes a model per test module, so scenarios in the same module share a
model: "Given" steps must converge to a state rather than assume a fresh model.
"""

import jubilant


def wait_settled(juju: jubilant.Juju, *apps: str, timeout: float = 15 * 60) -> None:
    """Wait until every given application is active and its agents idle."""
    juju.wait(
        lambda status: (
            jubilant.all_active(status, *apps) and jubilant.all_agents_idle(status, *apps)
        ),
        error=lambda status: jubilant.any_error(status, *apps),
        delay=10,
        successes=3,
        timeout=timeout,
    )


def ensure_deployed(juju: jubilant.Juju, app: str, charm: str, *, channel: str) -> None:
    """Deploy a collaborator charm from Charmhub, unless already present."""
    if app not in juju.status().apps:
        juju.deploy(charm, app, channel=channel, trust=True)
    wait_settled(juju, app)


def ensure_integrated(juju: jubilant.Juju, app: str, remote_endpoint: str) -> None:
    """Integrate ``app`` with ``remote_endpoint`` (``<app>:<endpoint>``), unless already done.

    Only the remote endpoint is named: Juju infers the local one from the interface, so
    the charm under test does not have to declare its endpoint names.
    """
    remote_app = remote_endpoint.split(":", 1)[0]
    relations = juju.status().apps[app].relations
    if not any(r.related_app == remote_app for rs in relations.values() for r in rs):
        juju.integrate(app, remote_endpoint)
    wait_settled(juju, app, remote_app)

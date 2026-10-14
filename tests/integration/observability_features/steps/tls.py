"""Steps about the charm serving its workload API over TLS."""

import socket
import ssl

import jubilant
from pytest_bdd import given, then, when
from tenacity import retry, stop_after_delay, wait_fixed

from observability_features.charm import CharmUnderTest
from observability_features.steps._juju import ensure_deployed, ensure_integrated

CA_APP = "ca"


@given("a certificates provider is deployed")
def a_certificates_provider_is_deployed(juju: jubilant.Juju):
    ensure_deployed(juju, CA_APP, "self-signed-certificates", channel="1/stable")


@given("the charm is integrated with the certificates provider")
@when("the charm is integrated with the certificates provider")
def the_charm_is_integrated_with_the_certificates_provider(
    juju: jubilant.Juju, charm_under_test: CharmUnderTest
):
    ensure_integrated(juju, charm_under_test.app, f"{CA_APP}:certificates")


@then("the workload API is served over HTTPS")
def the_workload_api_is_served_over_https(juju: jubilant.Juju, charm_under_test: CharmUnderTest):
    """Every unit completes a TLS handshake whose certificate chains to the CA and names the unit."""
    ca = juju.run(f"{CA_APP}/0", "get-ca-certificate").results["ca-certificate"]
    context = ssl.create_default_context(cadata=ca)
    status = juju.status()
    for unit, unit_status in status.apps[charm_under_test.app].units.items():
        _handshake(
            context,
            address=unit_status.address,
            port=charm_under_test.workload_port,
            hostname=_unit_fqdn(status.model.name, unit),
        )


def _unit_fqdn(model: str, unit: str) -> str:
    """In-cluster FQDN of a unit, as set in its server certificate's SANs."""
    app = unit.split("/")[0]
    return f"{unit.replace('/', '-')}.{app}-endpoints.{model}.svc.cluster.local"


@retry(stop=stop_after_delay(120), wait=wait_fixed(10), reraise=True)
def _handshake(context: ssl.SSLContext, *, address: str, port: int, hostname: str) -> None:
    # The workload may still be restarting with its new certificate after the model settles.
    with (
        socket.create_connection((address, port), timeout=10) as sock,
        context.wrap_socket(sock, server_hostname=hostname),
    ):
        pass

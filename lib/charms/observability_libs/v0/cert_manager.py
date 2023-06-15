# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""## Overview.

This document explains how to use the `CertManager` class to
create and manage TLS certificates through the `tls_certificates` interface.

The goal of the CertManager is to provide a wrapper to the `tls_certificates`
library functions to make the charm integration smoother.

## Library Usage

This library should be used to create a `CertManager` object, as per the
following example:

```python
cert_manager = CertManager(
    charm=self,
    peer_relation_name="replicas",
    cert_subject="unit_name",  # Optional
    key="cert-manager"  # Optional
)
```

This library requires a peer relation to be declared in the requirer's metadata. Peer relation data
is used to communicate the private key to all units. This is useful for "ingress per app", and is
required because in juju, only the leader has permissions to read app data. # FIXME is this still true
"""
import socket
from typing import Optional, Union
import json

try:
    from charms.tls_certificates_interface.v2.tls_certificates import (  # pyright: ignore
        AllCertificatesInvalidatedEvent,
        CertificateAvailableEvent,
        CertificateExpiringEvent,
        CertificateInvalidatedEvent,
        TLSCertificatesRequiresV2,
        generate_csr,
        generate_private_key,
    )
except ImportError:
    raise ImportError(
        "charms.tls_certificates_interface.v2.tls_certificates is missing; please get it through charmcraft fetch-lib"
    )
from ops.charm import CharmBase
from ops.model import Relation
from ops.framework import EventBase, EventSource, Object, ObjectEvents


LIBID = "deadbeef"
LIBAPI = 0
LIBPATCH = 1


class CertChanged(EventBase):
    """Event raised when a cert is changed (becomes available or revoked)."""


class CertManagerEvents(ObjectEvents):
    cert_changed = EventSource(CertChanged)


class CertManager(Object):
    """CertManager is used to wrap TLS Certificates management operations for charms.

    TODO: figure out if the constructor should take
        key_path: str,
        cert_path: str,
        ca_path: str,
     instead of charm code pushing & deleting them itself.

    TODO Use some sort of compound status

    CertManager manages one single cert.
    """
    on = CertManagerEvents()  # pyright: ignore

    def __init__(
        self,
        charm: CharmBase,
        *,
        peer_relation_name: str,
        certificates_relation_name: str = "certificates",
        cert_subject: Optional[str] = None,
        key: str = "cert-manager",  # TODO what to put here?
    ):
        super().__init__(charm, key)

        self.charm = charm
        self.cert_subject = charm.unit.name if not cert_subject else cert_subject
        self.peer_relation_name = peer_relation_name
        self.certificates_relation_name = certificates_relation_name

        self.certificates = TLSCertificatesRequiresV2(self.charm, self.certificates_relation_name)

        self.framework.observe(
            self.charm.on.certificates_relation_joined,  # pyright: ignore
            self._on_certificates_relation_joined,
        )
        self.framework.observe(
            self.certificates.on.certificate_available,  # pyright: ignore
            self._on_certificate_available,
        )
        self.framework.observe(
            self.certificates.on.certificate_expiring,  # pyright: ignore
            self._on_certificate_expiring,
        )
        self.framework.observe(
            self.certificates.on.certificate_invalidated,  # pyright: ignore
            self._on_certificate_invalidated,
        )
        self.framework.observe(
            self.certificates.on.all_certificates_invalidated,  # pyright: ignore
            self._on_all_certificates_invalidated,
        )

        # Peer relation events
        self.framework.observe(
            self.charm.on[self.peer_relation_name].relation_created, self._on_peer_relation_created
        )

    @property
    def _peer_relation(self) -> Optional[Relation]:
        """Return the peer relation."""
        return self.charm.model.get_relation(self.peer_relation_name, None)

    def _on_peer_relation_created(self, _):
        """Generate the private key and store it in a peer relation."""
        # We're in "relation-joined", so the relation should be there
        peer_relation = self._peer_relation  # FIXME either check it or remove this line

        # Just in case we already have a private key, do not overwrite it.
        # Not sure how this could happen.
        # TODO figure out how to go about key rotation.
        if not self._private_key:
            private_key = generate_private_key()
            self._private_key = private_key.decode()

        # Generate CSR here, in case peer events fired after tls-certificate relation events
        if not (self.charm.model.get_relation(self.certificates_relation_name)):
            # peer relation event happened to fire before tls-certificates events.
            # Abort, and let the "certificates joined" observer create the CSR.
            return

        self._generate_csr()

    @property
    def private_key(self) -> Optional[str]:
        if peer_relation := self._peer_relation:
            return peer_relation.data[self.charm.unit].get("private_key", None)
        return None

    def _on_certificates_relation_joined(self, _) -> None:
        """Generate the CSR and request the certificate creation."""
        if not self._peer_relation:
            # tls-certificates relation event happened to fire before peer events.
            # Abort, and let the "peer joined" relation create the CSR.
            return

        self._generate_csr()

    def _generate_csr(self):
        # At this point, assuming "peer joined" and "certificates joined" have already fired
        # so we must have a private_key entry in relation data at our disposal. Otherwise, 
        # traceback -> debug.

        # In case we already have a csr, do not overwrite it.
        if not self._csr:
            csr = generate_csr(
                private_key=self.private_key.encode(),
                subject=self.cert_subject,
                sans_dns=[socket.getfqdn()]  # FIXME make sure this works properly
            )
            self._csr = csr.decode()
            self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Get the certificate from the event and store it in a peer relation.

        Note: assuming "limit: 1" in metadata
        """
        # We need to store the ca cert and server cert somewhere it would persist across upgrades.
        # While we support Juju 2.9, the only option is peer data. When we drop 2.9, then secrets.

        # I think juju guarantees that a peer-created always fires before any regular
        # relation-changed. If that is not the case, we would need more guards and more paths.

        # Only store the certificate on the unit that requested it
        if event.certificate_signing_request == self._csr:
            self._ca_cert = event.ca
            self._server_cert = event.certificate
            self._chain = event.chain
            self.on.cert_changed.emit()  # pyright: ignore

    @property
    def key(self):
        return self._private_key

    @property
    def _private_key(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("private_key", None)
        return None

    @_private_key.setter
    def _private_key(self, value: str):
        if self._peer_relation:
            self._peer_relation.data[self.charm.unit].update({"private_key": value})

    @property
    def _csr(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("csr", None)
        return None

    @_csr.setter
    def _csr(self, value: str):
        if self._peer_relation:
            self._peer_relation.data[self.charm.unit].update({"csr": value})

    @property
    def _ca_cert(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("ca", None)
        return None

    @_ca_cert.setter
    def _ca_cert(self, value: str):
        if self._peer_relation:
            self._peer_relation.data[self.charm.unit].update({"ca": value})

    @property
    def cert(self):
        return self._server_cert

    @property
    def _server_cert(self) -> Optional[str]:
        if self._peer_relation:
            return self._peer_relation.data[self.charm.unit].get("certificate", None)
        return None

    @_server_cert.setter
    def _server_cert(self, value: str):
        if self._peer_relation:
            self._peer_relation.data[self.charm.unit].update({"certificate": value})

    @property
    def _chain(self) -> Optional[str]:  # FIXME check the typing: setter -> list, getter -> str
        if self._peer_relation:
            if chain := self._peer_relation.data[self.charm.unit].get("chain", None):
                return json.loads(chain)
        return None

    @_chain.setter
    def _chain(self, value: list):
        if self._peer_relation:
            self._peer_relation.data[self.charm.unit].update({"chain": json.dumps(value)})

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        """Generate a new CSR and request certificate renewal."""
        if event.certificate == self._server_cert:
            new_csr = generate_csr(
                private_key=self._private_key.encode(),
                subject=self.cert_subject,
            )
            self.certificates.request_certificate_renewal(
                old_certificate_signing_request=self._csr.encode(),
                new_certificate_signing_request=new_csr,
            )
            self._csr = new_csr.decode()

    def _certificate_revoked(self, event) -> None:
        """Remove the certificate from the peer relation and generate a new CSR."""
        # Note: assuming "limit: 1" in metadata
        # TODO: figure out what should happen with the existing csr after a "revoked"
        if event.certificate_signing_request == self._csr:
            self._ca_cert = ""
            self._server_cert = ""
            self._chain = ""
            self.on.cert_changed.emit()  # pyright: ignore

            new_csr = generate_csr(
                private_key=self._private_key.encode(),
                subject=self.cert_subject,
            )
            self._csr = new_csr.decode()
            self._server_cert = ""
            self._ca_cert = ""
            self._chain = ""

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        """Deal with certificate revocation and expiration."""
        self.on.cert_changed.emit()  # pyright: ignore
        # TODO: do we need to generate a new CSR?
        if self._peer_relation:
            if event.certificate_signing_request == self._csr:
                if event.reason == "revoked":
                    self._certificate_revoked(event)
                if event.reason == "expired":
                    self._ca_cert = ""
                    self._server_cert = ""
                    self._chain = ""
                    self._on_certificate_expiring(event)

    def _on_all_certificates_invalidated(self, event: AllCertificatesInvalidatedEvent) -> None:
        # Do what you want with this information, probably remove all certificates
        # TODO: do we need to generate a new CSR?
        # Note: assuming "limit: 1" in metadata
        self._ca_cert = ""
        self._server_cert = ""
        self._chain = ""
        self.on.cert_changed.emit()  # pyright: ignore

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
    private_key_password=b"some_password",
    cert_subject="unit_name",  # Optional
    peer_relation_name="replicas",  # Optional
    key="cert-manager"  # Optional
)
```

"""
from typing import Optional, Union

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
from ops.charm import CharmBase, RelationJoinedEvent
from ops.model import ActiveStatus, Relation, WaitingStatus
from ops.framework import EventBase, EventSource, Object, ObjectEvents


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

    CertManager manages one single cert.
    """
    on = CertManagerEvents()

    def __init__(
        self,
        charm: CharmBase,
        *,
        private_key_password: bytes = b"",
        cert_subject: Optional[str] = None,
        peer_relation_name: str = "replicas",
        key: str = "cert-manager",  # TODO what to put here?
    ):
        super().__init__(charm, key)

        self.charm = charm
        self.private_key_password = private_key_password
        self.cert_subject = charm.unit.name if not cert_subject else cert_subject
        self.peer_relation_name = peer_relation_name

        self.certificates = TLSCertificatesRequiresV2(self.charm, "certificates")

        # These will be updated with incoming events
        self.ca = None
        self.cert = None
        self.key = None

        self.framework.observe(self.charm.on.install, self._on_install)
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

    def _is_peer_relation_ready(self, event: EventBase) -> Optional[Relation]:
        """Check if the peer relation is ready for keys storage."""
        replicas_relation = self.charm.model.get_relation(self.peer_relation_name)
        if not replicas_relation:
            self.charm.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return None
        return replicas_relation

    def _on_install(self, event):
        """Generate the private key and store it in a peer relation."""
        if not self.charm.unit.is_leader():
            return

        if replicas_relation := self._is_peer_relation_ready(event):
            private_key = generate_private_key(self.private_key_password)
            replicas_relation.data[self.charm.app].update(
                {
                    "private_key_password": self.private_key_password.decode(),
                    "private_key": private_key.decode(),
                }
            )

    def _on_certificates_relation_joined(
        self,
        event: RelationJoinedEvent,
    ) -> None:
        """Generate the CSR and request the certificate creation."""
        if replicas_relation := self._is_peer_relation_ready(event):
            private_key_password = replicas_relation.data[self.charm.app].get(
                "private_key_password"
            )
            private_key = replicas_relation.data[self.charm.app].get("private_key")
            self.key = private_key or None
            if not private_key_password or not private_key:
                return  # TODO is return okay?
            csr = generate_csr(
                private_key=private_key.encode(),
                private_key_password=private_key_password.encode(),
                subject=self.cert_subject,
            )
            replicas_relation.data[self.charm.app].update({"csr": csr.decode()})
            self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Get the certificate from the event and store it in a peer relation."""
        # Note: assuming "limit: 1" in metadata
        self.ca = event.ca
        self.cert = event.certificate
        self.on.cert_changed.emit()

        if replicas_relation := self._is_peer_relation_ready(event):
            replicas_relation.data[self.charm.app].update({"certificate": event.certificate})
            replicas_relation.data[self.charm.app].update({"ca": event.ca})
            replicas_relation.data[self.charm.app].update(
                {"chain": event.chain}
            )  # pyright: ignore
            self.charm.unit.status = ActiveStatus()  # FIXME remove (compound status)

    def _on_certificate_expiring(
        self, event: Union[CertificateExpiringEvent, CertificateInvalidatedEvent]
    ) -> None:
        """Generate a new CSR and request certificate renewal."""
        if replicas_relation := self._is_peer_relation_ready(event):
            old_csr = replicas_relation.data[self.charm.app].get("csr")
            if not old_csr:
                return  # TODO what to do here? fail? should there always be a csr ?
            private_key_password = replicas_relation.data[self.charm.app].get(
                "private_key_password"
            )
            private_key = replicas_relation.data[self.charm.app].get("private_key")
            if not private_key_password or not private_key:
                return  # TODO is return okay ?
            new_csr = generate_csr(
                private_key=private_key.encode(),
                private_key_password=private_key_password.encode(),
                subject=self.cert_subject,
            )
            self.certificates.request_certificate_renewal(
                old_certificate_signing_request=old_csr.encode(),
                new_certificate_signing_request=new_csr,
            )
            replicas_relation.data[self.charm.app].update({"csr": new_csr.decode()})

    def _certificate_revoked(self, event) -> None:
        """Remove the certificate from the peer relation and generate a new CSR."""
        # Note: assuming "limit: 1" in metadata
        self.ca = None
        self.cert = None
        # FIXME what about key rotation? would we ever need to?
        self.on.cert_changed.emit()

        if replicas_relation := self._is_peer_relation_ready(event):
            old_csr = replicas_relation.data[self.charm.app].get("csr")
            if not old_csr:
                return  # TODO what to do here? fail? should there always be a csr ?
            private_key_password = replicas_relation.data[self.charm.app].get(
                "private_key_password"
            )
            private_key = replicas_relation.data[self.charm.app].get("private_key")
            if not private_key_password or not private_key:
                return  # TODO what to do if None? fail?
            new_csr = generate_csr(
                private_key=private_key.encode(),
                private_key_password=private_key_password.encode(),
                subject=self.cert_subject,
            )
            replicas_relation.data[self.charm.app].update({"csr": new_csr.decode()})
            replicas_relation.data[self.charm.app].pop("certificate")
            replicas_relation.data[self.charm.app].pop("ca")
            replicas_relation.data[self.charm.app].pop("chain")
            self.charm.unit.status = WaitingStatus("Waiting for new certificate")

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent) -> None:
        """Deal with certificate revocation and expiration."""
        self.ca = None
        self.cert = None
        self.on.cert_changed.emit()

        if self._is_peer_relation_ready(event):
            if event.reason == "revoked":
                self._certificate_revoked(event)
            if event.reason == "expired":
                self._on_certificate_expiring(event)

    def _on_all_certificates_invalidated(self, event: AllCertificatesInvalidatedEvent) -> None:
        # Do what you want with this information, probably remove all certificates

        # Note: assuming "limit: 1" in metadata
        self.ca = None
        self.cert = None
        self.on.cert_changed.emit()


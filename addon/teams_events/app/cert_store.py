from __future__ import annotations

import base64
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.oid import NameOID

log = logging.getLogger(__name__)

CERT_COMMON_NAME = "teams-events-notifications"
CERT_VALIDITY_YEARS = 10


@dataclass
class NotificationCert:
    """A self-signed X.509 cert + private key used for Graph change-notification
    resource-data encryption.
    """

    private_key: RSAPrivateKey
    certificate: x509.Certificate

    @property
    def cert_id(self) -> str:
        """Identifier we pass as `encryptionCertificateId` on subscription
        creation. We use the SHA-256 thumbprint so rotating the cert naturally
        changes the id.
        """
        thumbprint_bytes = self.certificate.fingerprint(hashes.SHA256())
        return thumbprint_bytes.hex()

    @property
    def public_cert_b64_der(self) -> str:
        """Base64-encoded DER of the X.509 certificate — the format Graph
        expects in `encryptionCertificate`.
        """
        der = self.certificate.public_bytes(serialization.Encoding.DER)
        return base64.b64encode(der).decode()


def load_or_generate(cert_path: Path, key_path: Path) -> NotificationCert:
    """Load a persisted cert+key pair, or generate a new one and persist it."""
    if cert_path.exists() and key_path.exists():
        log.info("Loading existing notification cert from %s", cert_path)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        private_key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None
        )
        if not isinstance(private_key, RSAPrivateKey):
            raise RuntimeError(f"Private key at {key_path} is not RSA")
        return NotificationCert(private_key=private_key, certificate=cert)

    log.info("Generating new notification cert + key at %s / %s", cert_path, key_path)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, CERT_COMMON_NAME)]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365 * CERT_VALIDITY_YEARS))
        .sign(private_key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return NotificationCert(private_key=private_key, certificate=certificate)

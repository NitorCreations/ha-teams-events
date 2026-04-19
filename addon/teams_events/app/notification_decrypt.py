from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .cert_store import NotificationCert

log = logging.getLogger(__name__)


class DecryptionError(RuntimeError):
    pass


def decrypt_encrypted_content(
    encrypted_content: dict[str, Any], cert: NotificationCert
) -> dict[str, Any]:
    """Decrypt a Microsoft Graph change notification's `encryptedContent`.

    Graph encrypts the resource data with AES-256-CBC using a per-notification
    symmetric key. The symmetric key is itself wrapped with RSA-OAEP-SHA1 using
    the public cert we supplied at subscription creation. A separate
    HMAC-SHA256 over the ciphertext (using the same symmetric key) provides
    tamper protection.

    Reference: "Decrypting notifications" in
    https://learn.microsoft.com/graph/change-notifications-with-resource-data
    """
    try:
        data_b64 = encrypted_content["data"]
        data_key_b64 = encrypted_content["dataKey"]
        signature_b64 = encrypted_content["dataSignature"]
    except KeyError as exc:
        raise DecryptionError(f"encryptedContent missing field: {exc}") from exc

    ciphertext = base64.b64decode(data_b64)
    wrapped_key = base64.b64decode(data_key_b64)
    expected_sig = base64.b64decode(signature_b64)

    try:
        symmetric_key = cert.private_key.decrypt(
            wrapped_key,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
    except Exception as exc:
        raise DecryptionError(f"RSA unwrap of dataKey failed: {exc}") from exc

    if len(symmetric_key) != 32:
        raise DecryptionError(
            f"Expected 32-byte AES key, got {len(symmetric_key)} bytes"
        )

    actual_sig = hmac.new(symmetric_key, ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_sig, expected_sig):
        raise DecryptionError("dataSignature HMAC verification failed")

    iv = symmetric_key[:16]
    decryptor = Cipher(algorithms.AES(symmetric_key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecryptionError(f"decrypted payload is not JSON: {exc}") from exc

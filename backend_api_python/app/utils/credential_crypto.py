"""Fernet encryption for persisted credentials and MFA secrets.

New installations use ``CREDENTIAL_ENCRYPTION_KEY`` so rotating the JWT/session
``SECRET_KEY`` does not make broker credentials unreadable. Ciphertexts created
by older releases remain readable through the legacy ``SECRET_KEY`` fallback.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def _secret_key() -> str:
    secret = (os.getenv("SECRET_KEY") or "").strip()
    if not secret:
        try:
            from app.config.settings import Config

            secret = str(Config.SECRET_KEY or "").strip()
        except Exception:
            secret = ""
    return secret


def _credential_key() -> str:
    return (os.getenv("CREDENTIAL_ENCRYPTION_KEY") or "").strip()


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encryption_secret() -> str:
    secret = _credential_key() or _secret_key()
    if not secret:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY must be set to encrypt persisted credentials"
        )
    return secret


def encrypt_credential_blob(plaintext_json: str) -> str:
    """Encrypt JSON text for storage in encrypted_config."""
    if plaintext_json is None:
        plaintext_json = ""
    f = _fernet(_encryption_secret())
    return f.encrypt(plaintext_json.encode("utf-8")).decode("ascii")


def decrypt_credential_blob(stored: Any) -> str:
    """
    Decrypt DB value to JSON text. Empty / None yields empty string.
    """
    if stored is None:
        return ""
    s = stored.decode("utf-8") if isinstance(stored, (bytes, bytearray)) else str(stored)
    s = s.strip()
    if not s:
        return ""
    secrets = []
    for candidate in (_credential_key(), _secret_key()):
        if candidate and candidate not in secrets:
            secrets.append(candidate)
    if not secrets:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY must be set to decrypt persisted credentials"
        )
    for secret in secrets:
        try:
            return _fernet(secret).decrypt(s.encode("ascii")).decode("utf-8")
        except InvalidToken:
            continue
    raise ValueError(
        "Cannot decrypt persisted credential with the configured encryption keys"
    )

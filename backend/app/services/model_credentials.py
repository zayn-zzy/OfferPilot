"""Encrypt per-account model API credentials before persisting them."""

from __future__ import annotations

import base64
import os
import secrets
import stat
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

KEY_BYTES = 32
NONCE_BYTES = 12
KEY_FILENAME = ".model-settings.key"


class ModelCredentialError(Exception):
    """Credential encryption material is missing or unusable."""


def _load_or_create_key(storage_dir: Path, *, create: bool) -> bytes:
    key_path = storage_dir.resolve() / KEY_FILENAME
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not key_path.exists() and create:
            try:
                descriptor = os.open(
                    key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                key = secrets.token_bytes(KEY_BYTES)
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(key)
                    key_file.flush()
                    os.fsync(key_file.fileno())

        if key_path.is_symlink() or not key_path.exists():
            raise ModelCredentialError("Model credential encryption key is unavailable")
        metadata = key_path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ModelCredentialError("Model credential encryption key is invalid")
        if metadata.st_mode & 0o077:
            os.chmod(key_path, 0o600)
        key = key_path.read_bytes()
        if len(key) != KEY_BYTES:
            raise ModelCredentialError("Model credential encryption key is invalid")
        return key
    except ModelCredentialError:
        raise
    except OSError as exc:
        raise ModelCredentialError("Model credential encryption key is unavailable") from exc


def encrypt_model_credential(
    settings: Settings,
    user_id: UUID,
    provider: str,
    credential: str,
) -> str:
    """Encrypt one non-empty credential with user/provider-bound associated data."""

    normalized = credential.strip()
    if not normalized:
        raise ValueError("Credential cannot be blank")
    key = _load_or_create_key(settings.storage_dir, create=True)
    nonce = secrets.token_bytes(NONCE_BYTES)
    associated_data = f"offerpilot:model-credential:v1:{user_id}:{provider}".encode()
    ciphertext = AESGCM(key).encrypt(nonce, normalized.encode("utf-8"), associated_data)
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"v1:{payload}"


def decrypt_model_credential(
    settings: Settings,
    user_id: UUID,
    provider: str,
    encrypted: str,
) -> str:
    """Decrypt a credential only for its original account and provider slot."""

    try:
        version, payload = encrypted.split(":", maxsplit=1)
        if version != "v1":
            raise ValueError("Unsupported ciphertext version")
        packed = base64.urlsafe_b64decode(payload.encode("ascii"))
        if len(packed) <= NONCE_BYTES:
            raise ValueError("Ciphertext is incomplete")
        nonce, ciphertext = packed[:NONCE_BYTES], packed[NONCE_BYTES:]
        key = _load_or_create_key(settings.storage_dir, create=False)
        associated_data = f"offerpilot:model-credential:v1:{user_id}:{provider}".encode()
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data).decode("utf-8")
    except ModelCredentialError:
        raise
    except (InvalidTag, UnicodeDecodeError, ValueError, OSError) as exc:
        raise ModelCredentialError("Model credential could not be decrypted") from exc

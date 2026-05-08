from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionKeyError(RuntimeError):
    pass


def validate_token_encryption_key() -> None:
    _get_fernet()


def _get_fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise TokenEncryptionKeyError(
            "TOKEN_ENCRYPTION_KEY is required for token encryption"
        )

    try:
        return Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise TokenEncryptionKeyError(
            "TOKEN_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def encrypt_token(raw_token: str) -> str:
    token = _get_fernet().encrypt(raw_token.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_token(auth_token_blob: str) -> str:
    try:
        token = _get_fernet().decrypt(auth_token_blob.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("auth_token_blob is not a valid encrypted token") from exc

    return token.decode("utf-8")

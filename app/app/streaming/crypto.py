from __future__ import annotations

import os

from cryptography.fernet import Fernet


def encrypt_token(raw_token: str) -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for token encryption")

    try:
        fernet = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    return fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_token(auth_token_blob: str) -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for token encryption")

    try:
        fernet = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    return fernet.decrypt(auth_token_blob.encode("utf-8")).decode("utf-8")

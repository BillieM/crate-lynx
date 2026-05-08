from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.streaming.crypto import (
    TokenEncryptionKeyError,
    decrypt_token,
    encrypt_token,
    validate_token_encryption_key,
)


def test_encrypt_and_decrypt_token_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    encrypted = encrypt_token("secret-token")

    assert encrypted != "secret-token"
    assert decrypt_token(encrypted) == "secret-token"


def test_encrypt_token_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(
        TokenEncryptionKeyError, match="TOKEN_ENCRYPTION_KEY is required"
    ):
        encrypt_token("secret-token")


def test_validate_token_encryption_key_rejects_invalid_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "invalid-key")

    with pytest.raises(TokenEncryptionKeyError, match="valid Fernet key"):
        validate_token_encryption_key()


def test_decrypt_token_rejects_invalid_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with pytest.raises(
        ValueError, match="auth_token_blob is not a valid encrypted token"
    ):
        decrypt_token("not-a-valid-fernet-token")

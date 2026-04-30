from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from db.crypto import decrypt_token, encrypt_token


def test_encrypt_and_decrypt_token_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    encrypted = encrypt_token("secret-token")

    assert encrypted != "secret-token"
    assert decrypt_token(encrypted) == "secret-token"


def test_encrypt_token_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY is required"):
        encrypt_token("secret-token")


def test_decrypt_token_rejects_invalid_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with pytest.raises(
        ValueError, match="auth_token_blob is not a valid encrypted token"
    ):
        decrypt_token("not-a-valid-fernet-token")

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select

from app.streaming_accounts import (
    YOUTUBE_MUSIC_PROVIDER,
    StreamingAccountStore,
    connect_youtube_music_account,
    metadata,
    streaming_accounts_table,
)
from app.youtube_music import YouTubeMusicOAuthCredentials


def test_connect_youtube_music_account_encrypts_and_persists_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    seen: dict[str, object] = {}

    def fake_setup_oauth(
        credentials: YouTubeMusicOAuthCredentials,
        *,
        filepath: str | Path | None = None,
        open_browser: bool = False,
    ) -> dict[str, str]:
        seen["credentials"] = credentials
        seen["filepath"] = filepath
        seen["open_browser"] = open_browser
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.setup_oauth",
        fake_setup_oauth,
    )

    account = connect_youtube_music_account(
        database_url=database_url,
        display_name="Billie",
        credentials=YouTubeMusicOAuthCredentials(
            client_id="client-id",
            client_secret="client-secret",
        ),
        token_filepath=tmp_path / "oauth.json",
        open_browser=True,
    )

    assert account == account.__class__(
        id=1,
        provider=YOUTUBE_MUSIC_PROVIDER,
        display_name="Billie",
    )
    assert seen == {
        "credentials": YouTubeMusicOAuthCredentials(
            client_id="client-id",
            client_secret="client-secret",
        ),
        "filepath": tmp_path / "oauth.json",
        "open_browser": True,
    }

    with engine.connect() as connection:
        stored_account = (
            connection.execute(select(streaming_accounts_table)).mappings().one()
        )

    assert stored_account["provider"] == YOUTUBE_MUSIC_PROVIDER
    assert stored_account["display_name"] == "Billie"
    assert stored_account["auth_token_blob"] != json.dumps(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        },
        sort_keys=True,
    )
    assert json.loads(_decrypt_token(stored_account["auth_token_blob"])) == {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
    }


def test_streaming_account_store_persists_encrypted_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-store.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    account = StreamingAccountStore(database_url).create_youtube_music_account(
        display_name="Listener",
        oauth_token={"refresh_token": "refresh-token"},
    )

    assert account == account.__class__(
        id=1,
        provider=YOUTUBE_MUSIC_PROVIDER,
        display_name="Listener",
    )

    with engine.connect() as connection:
        stored_account = (
            connection.execute(select(streaming_accounts_table)).mappings().one()
        )

    assert json.loads(_decrypt_token(stored_account["auth_token_blob"])) == {
        "refresh_token": "refresh-token"
    }


def _decrypt_token(auth_token_blob: str) -> str:
    key = os.environ["TOKEN_ENCRYPTION_KEY"]
    return (
        Fernet(key.encode("utf-8"))
        .decrypt(auth_token_blob.encode("utf-8"))
        .decode("utf-8")
    )

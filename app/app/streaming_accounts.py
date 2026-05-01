from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    select,
)

from app.youtube_music import YouTubeMusicAdapter, YouTubeMusicOAuthCredentials


YOUTUBE_MUSIC_PROVIDER = "youtube_music"

metadata = MetaData()

streaming_accounts_table = Table(
    "streaming_accounts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("provider", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("auth_token_blob", String, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)


@dataclass(frozen=True, slots=True)
class PersistedStreamingAccount:
    id: int
    provider: str
    display_name: str


@dataclass(frozen=True, slots=True)
class StreamingAccountRecord(PersistedStreamingAccount):
    created_at: datetime
    updated_at: datetime


class StreamingAccountStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def create_youtube_music_account(
        self,
        *,
        display_name: str,
        oauth_token: dict[str, Any],
    ) -> PersistedStreamingAccount:
        encrypted_token = encrypt_token(json.dumps(oauth_token, sort_keys=True))

        with self._engine.begin() as connection:
            result = connection.execute(
                insert(streaming_accounts_table).values(
                    provider=YOUTUBE_MUSIC_PROVIDER,
                    display_name=display_name,
                    auth_token_blob=encrypted_token,
                )
            )

        inserted_id = result.inserted_primary_key[0]
        if not isinstance(inserted_id, int):
            raise ValueError("Failed to persist streaming account")

        return PersistedStreamingAccount(
            id=inserted_id,
            provider=YOUTUBE_MUSIC_PROVIDER,
            display_name=display_name,
        )

    def list_accounts(self) -> list[StreamingAccountRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_accounts_table.c.id,
                    streaming_accounts_table.c.provider,
                    streaming_accounts_table.c.display_name,
                    streaming_accounts_table.c.created_at,
                    streaming_accounts_table.c.updated_at,
                ).order_by(streaming_accounts_table.c.id.asc())
            ).mappings()

            return [
                StreamingAccountRecord(
                    id=row["id"],
                    provider=row["provider"],
                    display_name=row["display_name"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]


def connect_youtube_music_account(
    *,
    database_url: str,
    display_name: str,
    credentials: YouTubeMusicOAuthCredentials,
    token_filepath: str | Path | None = None,
    open_browser: bool = False,
) -> PersistedStreamingAccount:
    oauth_token = YouTubeMusicAdapter.setup_oauth(
        credentials,
        filepath=token_filepath,
        open_browser=open_browser,
    )

    return StreamingAccountStore(database_url).create_youtube_music_account(
        display_name=display_name,
        oauth_token=oauth_token,
    )


def encrypt_token(raw_token: str) -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for token encryption")

    try:
        fernet = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    return fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

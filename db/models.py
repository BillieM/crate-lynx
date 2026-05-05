from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    metadata = metadata


class LocalTrack(Base):
    __tablename__ = "local_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    library_root_rel_path: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=True)
    beets_id: Mapped[int] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class FailedIngestionAttempt(Base):
    __tablename__ = "failed_ingestion_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str] = mapped_column(String, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    local_track_id: Mapped[int | None] = mapped_column(
        ForeignKey("local_tracks.id"),
        nullable=True,
    )


class IngestFolder(Base):
    __tablename__ = "ingest_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StreamingAccount(Base):
    __tablename__ = "streaming_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    auth_token_blob: Mapped[str] = mapped_column(String, nullable=False)
    auth_state: Mapped[str] = mapped_column(String, nullable=False)
    auth_error: Mapped[str] = mapped_column(String, nullable=True)
    auth_error_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StreamingPlaylist(Base):
    __tablename__ = "streaming_playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("streaming_accounts.id"),
        nullable=False,
    )
    provider_playlist_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StreamingTrack(Base):
    __tablename__ = "streaming_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_track_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    album: Mapped[str] = mapped_column(String, nullable=True)
    year: Mapped[int] = mapped_column(nullable=True)
    isrc: Mapped[str] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int] = mapped_column(nullable=True)


class PlaylistMembership(Base):
    __tablename__ = "playlist_membership"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("streaming_playlists.id"),
        nullable=False,
    )
    streaming_track_id: Mapped[int] = mapped_column(
        ForeignKey("streaming_tracks.id"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(nullable=False)


class SuggestedLink(Base):
    __tablename__ = "suggested_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    local_track_id: Mapped[int] = mapped_column(
        ForeignKey("local_tracks.id"),
        nullable=False,
    )
    streaming_track_id: Mapped[int] = mapped_column(
        ForeignKey("streaming_tracks.id"),
        nullable=False,
    )
    match_method: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FinalLink(Base):
    __tablename__ = "final_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    local_track_id: Mapped[int] = mapped_column(
        ForeignKey("local_tracks.id"),
        nullable=False,
        unique=True,
    )
    streaming_track_id: Mapped[int] = mapped_column(
        ForeignKey("streaming_tracks.id"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

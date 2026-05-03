from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
from urllib.request import urlopen

from sqlalchemy import create_engine, select
from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1, ID3, ID3NoHeaderError

from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.adapters.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicTrackMetadata,
)
from app.streaming.models import (
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore


class MetadataRescueError(RuntimeError):
    """Raised when local metadata rescue cannot be completed."""


@dataclass(frozen=True, slots=True)
class RescueMetadata:
    title: str
    artist: str
    album: str | None
    year: int | None
    album_art_url: str | None


@dataclass(frozen=True, slots=True)
class ArtworkPayload:
    data: bytes
    mime_type: str
    description: str = "Cover"
    picture_type: int = 3


def rescue_metadata(
    local_track_id: int,
    *,
    database_url: str | None = None,
    library_root: Path | str | None = None,
) -> RescueMetadata:
    resolved_database_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_database_url:
        raise MetadataRescueError("DATABASE_URL must be configured for metadata rescue")

    resolved_library_root = Path(
        library_root or os.environ.get("LIBRARY_ROOT", "/library")
    )
    engine = create_engine(resolved_database_url)

    with engine.connect() as connection:
        row = (
            connection.execute(
                select(
                    local_tracks_table.c.file_path,
                    streaming_tracks_table.c.provider_track_id,
                    streaming_tracks_table.c.title,
                    streaming_tracks_table.c.artist,
                    streaming_tracks_table.c.album,
                    streaming_tracks_table.c.year,
                    streaming_playlists_table.c.account_id,
                )
                .select_from(
                    final_links_table.join(
                        local_tracks_table,
                        local_tracks_table.c.id == final_links_table.c.local_track_id,
                    )
                    .join(
                        streaming_tracks_table,
                        streaming_tracks_table.c.id
                        == final_links_table.c.streaming_track_id,
                    )
                    .outerjoin(
                        playlist_membership_table,
                        playlist_membership_table.c.streaming_track_id
                        == streaming_tracks_table.c.id,
                    )
                    .outerjoin(
                        streaming_playlists_table,
                        streaming_playlists_table.c.id
                        == playlist_membership_table.c.playlist_id,
                    )
                )
                .where(final_links_table.c.local_track_id == local_track_id)
                .order_by(
                    streaming_playlists_table.c.account_id.asc(),
                    streaming_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .first()
        )

        if row is None:
            raise MetadataRescueError(
                f"No final link exists for local track {local_track_id}"
            )

        account_id = row["account_id"]
        if not isinstance(account_id, int):
            account_id = _fallback_account_id(connection)

    if account_id is None:
        raise MetadataRescueError(
            "No streaming account is available to fetch rescue metadata"
        )

    account = StreamingAccountStore(resolved_database_url).get_account(account_id)
    adapter = YouTubeMusicAdapter.from_browser_auth(account.browser_headers)
    fetched_metadata = adapter.get_track_metadata(row["provider_track_id"])
    metadata = _merge_metadata(row, fetched_metadata)
    artwork = _download_artwork(metadata.album_art_url)

    write_id3_tags(
        resolved_library_root / row["file_path"],
        metadata,
        artwork=artwork,
    )
    return metadata


def write_id3_tags(
    mp3_path: Path | str,
    metadata: RescueMetadata,
    *,
    artwork: ArtworkPayload | None = None,
) -> None:
    path = Path(mp3_path)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    for frame_id in ("TIT2", "TPE1", "TALB", "TDRC", "APIC"):
        tags.delall(frame_id)

    tags.add(TIT2(encoding=3, text=metadata.title))
    tags.add(TPE1(encoding=3, text=metadata.artist))

    if metadata.album:
        tags.add(TALB(encoding=3, text=metadata.album))

    if metadata.year is not None:
        tags.add(TDRC(encoding=3, text=str(metadata.year)))

    if artwork is not None:
        tags.add(
            APIC(
                encoding=3,
                mime=artwork.mime_type,
                type=artwork.picture_type,
                desc=artwork.description,
                data=artwork.data,
            )
        )

    tags.save(path)


def _fallback_account_id(connection) -> int | None:
    row = connection.execute(
        select(streaming_accounts_table.c.id).order_by(
            streaming_accounts_table.c.id.asc()
        )
    ).first()
    if row is None:
        return None
    account_id = row[0]
    return account_id if isinstance(account_id, int) else None


def _merge_metadata(
    row,
    fetched_metadata: YouTubeMusicTrackMetadata,
) -> RescueMetadata:
    title = fetched_metadata.title or row["title"]
    artist = fetched_metadata.artist or row["artist"]
    if not title or not artist:
        raise MetadataRescueError(
            "Streaming metadata is missing required title or artist fields"
        )

    album = (
        fetched_metadata.album if fetched_metadata.album is not None else row["album"]
    )
    year = fetched_metadata.year if fetched_metadata.year is not None else row["year"]

    return RescueMetadata(
        title=title,
        artist=artist,
        album=album,
        year=year,
        album_art_url=fetched_metadata.album_art_url,
    )


def _download_artwork(album_art_url: str | None) -> ArtworkPayload | None:
    if not album_art_url:
        return None

    with urlopen(album_art_url, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type")

    if not data:
        return None

    mime_type = _resolve_mime_type(album_art_url, content_type)
    return ArtworkPayload(data=data, mime_type=mime_type)


def _resolve_mime_type(url: str, content_type: str | None) -> str:
    if isinstance(content_type, str) and content_type:
        return content_type.split(";", 1)[0].strip()

    guessed_type, _ = mimetypes.guess_type(url)
    if guessed_type:
        return guessed_type

    return "image/jpeg"

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import create_engine, select

from app.links.store import final_links_table
from app.streaming.models import (
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


@dataclass(frozen=True, slots=True)
class MissingLocallyTrackRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_count: int
    playlist_titles: list[str]


@dataclass(slots=True)
class _MissingLocallyAccumulator:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_titles_by_id: dict[int, str] = field(default_factory=dict)

    def to_record(self) -> MissingLocallyTrackRecord:
        return MissingLocallyTrackRecord(
            id=self.id,
            provider_track_id=self.provider_track_id,
            title=self.title,
            artist=self.artist,
            album=self.album,
            duration_ms=self.duration_ms,
            playlist_count=len(self.playlist_titles_by_id),
            playlist_titles=list(self.playlist_titles_by_id.values()),
        )


class MaintenanceStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def list_missing_locally(self) -> list[MissingLocallyTrackRecord]:
        query = (
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.provider_track_id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.duration_ms,
                streaming_playlists_table.c.id.label("playlist_id"),
                streaming_playlists_table.c.title.label("playlist_title"),
            )
            .select_from(
                streaming_tracks_table.outerjoin(
                    final_links_table,
                    final_links_table.c.streaming_track_id
                    == streaming_tracks_table.c.id,
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
            .where(final_links_table.c.id.is_(None))
            .order_by(
                streaming_tracks_table.c.id.asc(),
                streaming_playlists_table.c.title.asc(),
                streaming_playlists_table.c.id.asc(),
            )
        )

        tracks_by_id: dict[int, _MissingLocallyAccumulator] = {}
        with self._engine.connect() as connection:
            for row in connection.execute(query).mappings():
                track = tracks_by_id.setdefault(
                    row["id"],
                    _MissingLocallyAccumulator(
                        id=row["id"],
                        provider_track_id=row["provider_track_id"],
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        duration_ms=row["duration_ms"],
                    ),
                )
                if row["playlist_id"] is not None:
                    track.playlist_titles_by_id[row["playlist_id"]] = row[
                        "playlist_title"
                    ]

        return [track.to_record() for track in tracks_by_id.values()]

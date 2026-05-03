from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from mutagen.id3 import ID3
from sqlalchemy import create_engine, insert

from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.rescue.metadata import RescueMetadata, rescue_metadata
from app.streaming.models import (
    metadata as streaming_metadata,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore


def test_rescue_metadata_writes_tags_from_linked_streaming_track(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'rescue.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    library_root = tmp_path / "library"
    track_path = library_root / "Artist" / "track.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"")

    account = StreamingAccountStore(database_url).create_youtube_music_account(
        display_name="Main Account",
        browser_headers={"Authorization": "Bearer token"},
    )

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=5,
                file_path="Artist/track.mp3",
                library_root_rel_path="Artist/track.mp3",
                fingerprint="fp-5",
                beets_id=5,
            )
        )
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=account.id,
                provider_playlist_id="PL7",
                title="Rescue Mix",
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Stored Title",
                artist="Stored Artist",
                album="Stored Album",
                year=2019,
                isrc=None,
                duration_ms=180000,
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=5,
                streaming_track_id=9,
            )
        )

    seen: dict[str, object] = {}

    class FakeAdapter:
        def get_track_metadata(self, provider_track_id: str) -> RescueMetadata:
            seen["provider_track_id"] = provider_track_id
            return RescueMetadata(
                title="Rescue Title",
                artist="Rescue Artist",
                album="Rescue Album",
                year=2022,
                album_art_url="https://img.example/cover.jpg",
            )

    monkeypatch.setattr(
        "app.rescue.metadata.YouTubeMusicAdapter.from_browser_auth",
        lambda browser_headers: (
            seen.setdefault("browser_headers", browser_headers),
            FakeAdapter(),
        )[1],
    )
    monkeypatch.setattr(
        "app.rescue.metadata._download_artwork",
        lambda album_art_url: (
            seen.setdefault("album_art_url", album_art_url),
            type(
                "Artwork",
                (),
                {
                    "data": b"cover-bytes",
                    "mime_type": "image/jpeg",
                    "description": "Cover",
                    "picture_type": 3,
                },
            )(),
        )[1],
    )

    metadata = rescue_metadata(
        5,
        database_url=database_url,
        library_root=library_root,
    )

    assert metadata == RescueMetadata(
        title="Rescue Title",
        artist="Rescue Artist",
        album="Rescue Album",
        year=2022,
        album_art_url="https://img.example/cover.jpg",
    )
    assert seen == {
        "browser_headers": {"Authorization": "Bearer token"},
        "provider_track_id": "ytm-9",
        "album_art_url": "https://img.example/cover.jpg",
    }

    tags = ID3(track_path)
    assert tags.getall("TIT2")[0].text == ["Rescue Title"]
    assert tags.getall("TPE1")[0].text == ["Rescue Artist"]
    assert tags.getall("TALB")[0].text == ["Rescue Album"]
    assert str(tags.getall("TDRC")[0].text[0]) == "2022"
    apic = tags.getall("APIC")[0]
    assert apic.mime == "image/jpeg"
    assert apic.data == b"cover-bytes"

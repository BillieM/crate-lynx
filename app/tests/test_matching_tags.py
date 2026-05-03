from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, insert

from app.local_tracks.store import local_tracks_table, metadata as local_metadata
from app.matching import ConfidenceBand, TagMatcher
from app.streaming.models import metadata as streaming_metadata
from app.streaming.models import streaming_tracks_table


def test_tag_matcher_returns_best_high_confidence_match(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    streaming_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="abc123",
                beets_id=42,
            )
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "provider_track_id": "yt-1",
                    "title": "Track",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": None,
                    "duration_ms": 180000,
                },
                {
                    "provider_track_id": "yt-2",
                    "title": "Different Song",
                    "artist": "Another Artist",
                    "album": "Elsewhere",
                    "year": 2024,
                    "isrc": None,
                    "duration_ms": 180000,
                },
            ],
        )

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT)"
        )
        connection.execute(
            "INSERT INTO items (id, title, artist, album) VALUES (?, ?, ?, ?)",
            (42, " Track ", "ARTIST", "Album"),
        )
        connection.commit()

    result = TagMatcher(database_url=database_url, beets_library=beets_library).match(1)

    assert result is not None
    assert result.local_track_id == 1
    assert result.streaming_track_id == 1
    assert result.match_method == "tags"
    assert result.score == 1.0
    assert result.confidence_band is ConfidenceBand.HIGH


def test_tag_matcher_returns_medium_confidence_when_score_hits_threshold(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    streaming_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="abc123",
                beets_id=7,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="yt-1",
                title="Aaaa",
                artist="Bbbb",
                album=None,
                year=2024,
                isrc=None,
                duration_ms=180000,
            )
        )

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT)"
        )
        connection.execute(
            "INSERT INTO items (id, title, artist, album) VALUES (?, ?, ?, ?)",
            (7, "Aaab", "Bbbc", None),
        )
        connection.commit()

    result = TagMatcher(database_url=database_url, beets_library=beets_library).match(1)

    assert result is not None
    assert result.streaming_track_id == 1
    assert result.score == 0.75
    assert result.confidence_band is ConfidenceBand.MEDIUM


def test_tag_matcher_returns_low_confidence_when_score_is_below_threshold(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    streaming_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="abc123",
                beets_id=9,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="yt-1",
                title="Nope",
                artist="Mismatch",
                album=None,
                year=2024,
                isrc=None,
                duration_ms=180000,
            )
        )

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT)"
        )
        connection.execute(
            "INSERT INTO items (id, title, artist, album) VALUES (?, ?, ?, ?)",
            (9, "Aaab", "Bbbc", None),
        )
        connection.commit()

    result = TagMatcher(database_url=database_url, beets_library=beets_library).match(1)

    assert result is not None
    assert result.streaming_track_id == 1
    assert result.score < 0.5
    assert result.confidence_band is ConfidenceBand.LOW


def test_tag_matcher_returns_none_when_beets_item_has_no_title_or_artist(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    streaming_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="abc123",
                beets_id=11,
            )
        )

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT)"
        )
        connection.execute(
            "INSERT INTO items (id, title, artist, album) VALUES (?, ?, ?, ?)",
            (11, None, "Artist", "Album"),
        )
        connection.commit()

    result = TagMatcher(database_url=database_url, beets_library=beets_library).match(1)

    assert result is None

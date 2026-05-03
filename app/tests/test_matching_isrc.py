from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, insert

from app.local_tracks.store import local_tracks_table, metadata as local_metadata
from app.matching import ConfidenceBand, IsrcMatcher
from app.streaming.models import metadata as streaming_metadata
from app.streaming.models import streaming_tracks_table


def test_isrc_matcher_returns_high_confidence_match(tmp_path: Path) -> None:
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
            insert(streaming_tracks_table).values(
                provider_track_id="yt-1",
                title="Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="gbum72105976",
                duration_ms=180000,
            )
        )

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, isrc TEXT)")
        connection.execute(
            "INSERT INTO items (id, isrc) VALUES (?, ?)",
            (42, " GBUM72105976 "),
        )
        connection.commit()

    result = IsrcMatcher(database_url=database_url, beets_library=beets_library).match(
        1
    )

    assert result is not None
    assert result.local_track_id == 1
    assert result.streaming_track_id == 1
    assert result.match_method == "isrc"
    assert result.score == 1.0
    assert result.confidence_band is ConfidenceBand.HIGH


def test_isrc_matcher_returns_none_when_beets_item_has_no_isrc(tmp_path: Path) -> None:
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

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, isrc TEXT)")
        connection.execute("INSERT INTO items (id, isrc) VALUES (?, ?)", (7, None))
        connection.commit()

    result = IsrcMatcher(database_url=database_url, beets_library=beets_library).match(
        1
    )

    assert result is None


def test_isrc_matcher_returns_none_when_streaming_track_is_missing(
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

    beets_library = tmp_path / "library.db"
    with sqlite3.connect(beets_library) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, isrc TEXT)")
        connection.execute(
            "INSERT INTO items (id, isrc) VALUES (?, ?)",
            (9, "USQX92200001"),
        )
        connection.commit()

    result = IsrcMatcher(database_url=database_url, beets_library=beets_library).match(
        1
    )

    assert result is None

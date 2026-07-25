from __future__ import annotations

from pathlib import Path

import pytest
from app.autopilot.exports import (
    normalize_recipe_export_config,
    refresh_recipe_exports,
    validate_recipe_export_config,
)
from app.ingestion.beets_mirror import beets_items_table
from app.ingestion.beets_mirror import metadata as beets_metadata
from app.local_tracks.store import local_tracks_table
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.models import m3u_export_profiles_table
from app.m3u.models import metadata as m3u_metadata
from app.sonic.models import (
    generated_playlist_tracks_table,
    generated_playlists_table,
    playlist_generation_runs_table,
)
from app.sonic.models import (
    metadata as sonic_metadata,
)
from app.streaming.models import metadata as streaming_metadata
from sqlalchemy import create_engine, insert


def _engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'exports.db'}")
    for table_metadata in (
        beets_metadata,
        local_tracks_metadata,
        m3u_metadata,
        sonic_metadata,
        streaming_metadata,
    ):
        table_metadata.create_all(engine)
    return engine


def test_export_config_defaults_to_leaf_only_and_rejects_bad_values() -> None:
    config = normalize_recipe_export_config(
        {"enabled": True, "profile_id": 1, "formats": ["m3u"]}
    )

    assert config is not None
    assert config.scope == "leaf_only"
    assert config.path_format == "absolute"

    with pytest.raises(ValueError, match="Unsupported autopilot export scope"):
        normalize_recipe_export_config(
            {
                "enabled": True,
                "profile_id": 1,
                "formats": ["m3u"],
                "scope": "../../library",
            }
        )


def test_export_config_validation_rejects_unknown_or_missing_profile(tmp_path) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(ValueError, match="Unsupported autopilot export config"):
        validate_recipe_export_config(
            engine=engine,
            raw={"enabled": False, "format": "m3u"},
        )
    with pytest.raises(ValueError, match="M3U export profile not found: 999"):
        validate_recipe_export_config(
            engine=engine,
            raw={
                "enabled": True,
                "profile_id": 999,
                "formats": ["m3u"],
                "path_format": "absolute",
                "scope": "leaf_only",
            },
        )


def test_recipe_export_materializes_leaf_playlists_with_atomic_swap(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        profile_id = connection.execute(
            insert(m3u_export_profiles_table).values(
                name="DJ laptop",
                library_path="/Music",
                is_default=True,
            )
        ).inserted_primary_key[0]
        run_id = connection.execute(
            insert(playlist_generation_runs_table).values(
                status="completed",
                source_filter_json={"source_type": "all_local"},
                generation_config_json={},
                run_name="Recipe",
                trigger="autopilot",
            )
        ).inserted_primary_key[0]
        root_id = connection.execute(
            insert(generated_playlists_table).values(
                run_id=run_id,
                parent_playlist_id=None,
                depth=0,
                position=0,
                name="Parent",
                summary_json={},
                track_count=2,
            )
        ).inserted_primary_key[0]
        leaf_ids = []
        for position, name in enumerate(("Leaf A", "Leaf B"), start=1):
            leaf_ids.append(
                connection.execute(
                    insert(generated_playlists_table).values(
                        run_id=run_id,
                        parent_playlist_id=root_id,
                        depth=1,
                        position=position,
                        name=name,
                        summary_json={},
                        track_count=1,
                    )
                ).inserted_primary_key[0]
            )
        for index, leaf_id in enumerate(leaf_ids, start=1):
            beets_id = connection.execute(
                insert(beets_items_table).values(
                    title=f"Track {index}",
                    artist="Artist",
                    album="Album",
                    length=240.0,
                )
            ).inserted_primary_key[0]
            local_track_id = connection.execute(
                insert(local_tracks_table).values(
                    file_path=f"Artist/Track {index}.mp3",
                    library_root_rel_path=f"Artist/Track {index}.mp3",
                    beets_id=beets_id,
                )
            ).inserted_primary_key[0]
            connection.execute(
                insert(generated_playlist_tracks_table).values(
                    generated_playlist_id=leaf_id,
                    local_track_id=local_track_id,
                    position=1,
                )
            )

    export_root = tmp_path / "exports"
    result = refresh_recipe_exports(
        engine=engine,
        export_config={
            "enabled": True,
            "profile_id": profile_id,
            "formats": ["m3u", "m3u8"],
            "path_format": "absolute",
            "scope": "leaf_only",
        },
        recipe_id=7,
        run_id=run_id,
        root=export_root,
    )

    assert result is not None
    assert result.playlist_count == 2
    assert result.file_count == 4
    assert result.directory.is_symlink()
    files = sorted(path.name for path in result.directory.iterdir())
    assert len(files) == 4
    assert all("Parent" not in filename for filename in files)
    assert all(
        line.startswith("/Music/")
        for path in result.directory.iterdir()
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    )

    second = refresh_recipe_exports(
        engine=engine,
        export_config={
            "enabled": True,
            "profile_id": profile_id,
            "formats": ["m3u"],
            "scope": "leaf_only",
        },
        recipe_id=7,
        run_id=run_id,
        root=export_root,
    )
    assert second is not None
    assert second.directory.is_symlink()
    assert len(list(second.directory.iterdir())) == 2

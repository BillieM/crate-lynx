from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, delete, select, update

from app.ingestion.beets_mirror_backfill import backfill_beets_mirror
from app.ingestion.beets_mirror_sync import decode_beets_path
from app.ingestion.failures import failed_ingestion_attempts_table
from app.ingestion.pipeline import FingerprintGenerator, IngestionCommandError
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.pipeline import suggested_links_table


logger = logging.getLogger(__name__)


def main() -> None:
    args = _parse_args()
    database_url = os.environ["DATABASE_URL"]
    library_root = Path(os.environ.get("LIBRARY_ROOT", "/music")).resolve()
    beets_library = Path(os.environ.get("BEETS_LIBRARY", "/data/beets/library.db"))
    staging_root = Path(
        os.environ.get("INGESTION_STAGING_ROOT", "/tmp/crate-lynx-ingestion-staging")
    )

    engine = create_engine(database_url)
    actions: list[str] = []

    with engine.begin() as connection:
        actions.extend(
            _repair_stale_failures(
                connection,
                apply=args.apply,
            )
        )
        actions.extend(
            _repair_duplicate_local_tracks(
                connection,
                apply=args.apply,
            )
        )
        actions.extend(
            _repair_beets_mirror(
                connection,
                beets_library=beets_library,
                apply=args.apply,
            )
        )
        inserted_track_ids = _repair_missing_local_tracks(
            connection,
            beets_library=beets_library,
            library_root=library_root,
            apply=args.apply,
        )
        actions.extend(
            f"insert local_track id={track_id} from missing Beets item"
            for track_id in inserted_track_ids
        )

    actions.extend(_repair_zero_byte_staging_files(staging_root, apply=args.apply))

    if args.apply and args.enqueue_matching:
        enqueued_ids = _enqueue_matching_jobs(inserted_track_ids)
        actions.extend(
            f"enqueue matching for local_track id={track_id}"
            for track_id in enqueued_ids
        )

    if not actions:
        print("No ingestion repair actions needed.")
        return

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {len(actions)} action(s)")
    for action in actions:
        print(f"- {action}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair stale ingestion failures and local track rows."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repair actions. Without this flag the command only reports actions.",
    )
    parser.add_argument(
        "--enqueue-matching",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enqueue matching jobs for newly inserted local tracks when applying.",
    )
    return parser.parse_args()


def _repair_stale_failures(connection, *, apply: bool) -> list[str]:
    rows = connection.execute(select(failed_ingestion_attempts_table)).mappings().all()
    stale_ids = [row["id"] for row in rows if not Path(row["source_path"]).exists()]

    if apply and stale_ids:
        connection.execute(
            delete(failed_ingestion_attempts_table).where(
                failed_ingestion_attempts_table.c.id.in_(stale_ids)
            )
        )

    return [
        f"delete stale failed_ingestion_attempt id={row_id}" for row_id in stale_ids
    ]


def _repair_duplicate_local_tracks(connection, *, apply: bool) -> list[str]:
    rows = (
        connection.execute(
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.file_path,
                local_tracks_table.c.beets_id,
            ).where(local_tracks_table.c.beets_id.is_not(None))
        )
        .mappings()
        .all()
    )
    final_linked_ids = set(
        connection.execute(select(final_links_table.c.local_track_id)).scalars()
    )

    ids_by_beets_id: dict[int, list[int]] = {}
    path_by_id: dict[int, str] = {}
    for row in rows:
        beets_id = row["beets_id"]
        if not isinstance(beets_id, int):
            continue
        ids_by_beets_id.setdefault(beets_id, []).append(row["id"])
        path_by_id[row["id"]] = row["file_path"]

    remove_ids: list[int] = []
    actions: list[str] = []
    for beets_id, ids in sorted(ids_by_beets_id.items()):
        if len(ids) < 2:
            continue
        linked_ids = [track_id for track_id in ids if track_id in final_linked_ids]
        keep_id = min(linked_ids or ids)
        duplicates = [track_id for track_id in ids if track_id != keep_id]
        remove_ids.extend(duplicates)
        for track_id in duplicates:
            actions.append(
                "delete duplicate local_track "
                f"id={track_id} beets_id={beets_id} path={path_by_id[track_id]!r}; "
                f"keep id={keep_id}"
            )

    if apply and remove_ids:
        connection.execute(
            delete(suggested_links_table).where(
                suggested_links_table.c.local_track_id.in_(remove_ids)
            )
        )
        connection.execute(
            update(failed_ingestion_attempts_table)
            .where(failed_ingestion_attempts_table.c.local_track_id.in_(remove_ids))
            .values(local_track_id=None)
        )
        connection.execute(
            delete(local_tracks_table).where(local_tracks_table.c.id.in_(remove_ids))
        )

    return actions


def _repair_beets_mirror(
    connection,
    *,
    beets_library: Path,
    apply: bool,
) -> list[str]:
    return backfill_beets_mirror(
        connection,
        beets_library=beets_library,
        apply=apply,
    )


def _repair_missing_local_tracks(
    connection,
    *,
    beets_library: Path,
    library_root: Path,
    apply: bool,
) -> list[int]:
    known_beets_ids = set(
        connection.execute(
            select(local_tracks_table.c.beets_id).where(
                local_tracks_table.c.beets_id.is_not(None)
            )
        ).scalars()
    )
    inserted_ids: list[int] = []

    for beets_id, library_path in _iter_current_beets_items(
        beets_library=beets_library,
        library_root=library_root,
    ):
        if beets_id in known_beets_ids:
            continue

        relative_path = str(library_path.resolve().relative_to(library_root))
        fingerprint = _fingerprint_or_none(library_path)
        if not apply:
            inserted_ids.append(beets_id)
            continue

        result = connection.execute(
            local_tracks_table.insert().values(
                file_path=relative_path,
                library_root_rel_path=relative_path,
                fingerprint=fingerprint,
                beets_id=beets_id,
            )
        )
        inserted_id = result.inserted_primary_key[0]
        if isinstance(inserted_id, int):
            inserted_ids.append(inserted_id)

    return inserted_ids


def _iter_current_beets_items(
    *,
    beets_library: Path,
    library_root: Path,
) -> list[tuple[int, Path]]:
    if not beets_library.exists():
        return []

    with sqlite3.connect(beets_library) as connection:
        rows = connection.execute("SELECT id, path FROM items ORDER BY id").fetchall()

    items: list[tuple[int, Path]] = []
    for beets_id, raw_path in rows:
        library_path = Path(decode_beets_path(raw_path))
        resolved_path = library_path.resolve()
        try:
            resolved_path.relative_to(library_root)
        except ValueError:
            continue
        if resolved_path.exists() and resolved_path.is_file():
            items.append((int(beets_id), resolved_path))

    return items


def _fingerprint_or_none(library_path: Path) -> str | None:
    try:
        return FingerprintGenerator().generate(library_path)
    except (FileNotFoundError, IngestionCommandError, ValueError):
        logger.exception("Failed to fingerprint library_path=%s", library_path)
        return None


def _repair_zero_byte_staging_files(staging_root: Path, *, apply: bool) -> list[str]:
    if not staging_root.exists() or not staging_root.is_dir():
        return []

    zero_byte_files = [
        path
        for path in staging_root.iterdir()
        if path.is_file() and path.stat().st_size == 0
    ]
    if apply:
        for path in zero_byte_files:
            path.unlink()

    return [f"delete zero-byte staging file {path}" for path in zero_byte_files]


def _enqueue_matching_jobs(local_track_ids: list[int]) -> list[int]:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return []

    enqueuer = MatchingJobEnqueuer(redis_url)
    enqueued_ids: list[int] = []
    for local_track_id in local_track_ids:
        enqueuer.enqueue(local_track_id)
        enqueued_ids.append(local_track_id)
    return enqueued_ids


if __name__ == "__main__":
    main()

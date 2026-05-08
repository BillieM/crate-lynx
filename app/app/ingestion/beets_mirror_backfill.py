from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator, Sequence
from itertools import islice
import logging
import os
from pathlib import Path
import sqlite3
import sys
from typing import TypeVar

from sqlalchemy import select

from app.core.db import create_database_engine
from app.ingestion.beets_mirror import beets_albums_table, beets_items_table
from app.ingestion.beets_mirror_sync import (
    iter_all_albums,
    iter_all_items,
    upsert_album,
    upsert_item,
)
from app.local_tracks.store import local_tracks_table


BEETS_MIRROR_BACKFILL_CHUNK_SIZE = 500
T = TypeVar("T")
logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> None:
    _configure_cli_logging()
    args = _parse_args(argv)
    database_url = os.environ["DATABASE_URL"]
    beets_library = Path(os.environ["BEETS_LIBRARY"])

    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        actions = backfill_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=args.apply,
        )

    _log_actions(actions, apply=args.apply)


def backfill_beets_mirror(
    connection,
    *,
    beets_library: Path,
    apply: bool,
) -> list[str]:
    if not beets_library.exists():
        return []

    actions: list[str] = []
    existing_item_ids = set(
        connection.execute(select(beets_items_table.c.beets_id)).scalars()
    )
    existing_album_ids = set(
        connection.execute(select(beets_albums_table.c.beets_album_id)).scalars()
    )
    current_item_ids: set[int] = set()
    current_album_ids: set[int] = set()

    with sqlite3.connect(beets_library) as sqlite_connection:
        for item_chunk in _batched(
            iter_all_items(sqlite_connection),
            BEETS_MIRROR_BACKFILL_CHUNK_SIZE,
        ):
            for item_row in item_chunk:
                current_item_ids.add(item_row.beets_id)
                status = (
                    upsert_item(connection, item_row)
                    if apply
                    else _mirror_status(item_row.beets_id, existing_item_ids)
                )
                actions.append(
                    f"{status} beets_mirror item beets_id={item_row.beets_id}"
                )

        for album_chunk in _batched(
            iter_all_albums(sqlite_connection),
            BEETS_MIRROR_BACKFILL_CHUNK_SIZE,
        ):
            for album_row in album_chunk:
                current_album_ids.add(album_row.beets_album_id)
                status = (
                    upsert_album(connection, album_row)
                    if apply
                    else _mirror_status(album_row.beets_album_id, existing_album_ids)
                )
                actions.append(
                    f"{status} beets_mirror album "
                    f"beets_album_id={album_row.beets_album_id}"
                )

    mirrored_item_ids = set(
        connection.execute(select(beets_items_table.c.beets_id)).scalars()
    )
    for beets_id in sorted(mirrored_item_ids - current_item_ids):
        actions.append(f"stale_mirror_items beets_id={beets_id} missing from Beets")

    mirrored_album_ids = set(
        connection.execute(select(beets_albums_table.c.beets_album_id)).scalars()
    )
    for beets_album_id in sorted(mirrored_album_ids - current_album_ids):
        actions.append(
            f"stale_mirror_albums beets_album_id={beets_album_id} missing from Beets"
        )

    local_track_rows = (
        connection.execute(
            select(local_tracks_table.c.id, local_tracks_table.c.beets_id).where(
                local_tracks_table.c.beets_id.is_not(None)
            )
        )
        .mappings()
        .all()
    )
    for row in local_track_rows:
        beets_id = row["beets_id"]
        if isinstance(beets_id, int) and beets_id not in current_item_ids:
            actions.append(
                "stale_local_track_beets_ids "
                f"local_track_id={row['id']} beets_id={beets_id} missing from Beets"
            )

    return actions


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Beets SQLite metadata into the Postgres mirror tables."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply mirror upserts. Without this flag the command only reports actions.",
    )
    return parser.parse_args(argv)


def _configure_cli_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stdout,
    )


def _log_actions(actions: list[str], *, apply: bool) -> None:
    if not actions:
        logger.info("No Beets mirror backfill actions needed.")
        return

    mode = "APPLY" if apply else "DRY-RUN"
    logger.info("%s: %s action(s)", mode, len(actions))
    for action in actions:
        logger.info("- %s", action)


def _mirror_status(entity_id: int, existing_ids: set[int]) -> str:
    return "updated" if entity_id in existing_ids else "inserted"


def _batched(
    rows: Iterable[T],
    size: int,
) -> Iterator[tuple[T, ...]]:
    iterator = iter(rows)
    while batch := tuple(islice(iterator, size)):
        yield batch


if __name__ == "__main__":
    main()

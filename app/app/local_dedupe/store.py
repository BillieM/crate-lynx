from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import hashlib
import os
import re
import shutil
import sqlite3
import unicodedata

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.isrc import normalize_isrc_code
from app.ingestion.beets_mirror import beets_item_attributes_table, beets_items_table
from app.ingestion.failures import failed_ingestion_attempts_table
from app.links.store import final_links_table
from app.local_dedupe.models import (
    LOCAL_DEDUPE_ACTION_DISMISSED,
    LOCAL_DEDUPE_ACTION_RESOLVED,
    LOCAL_DEDUPE_DURATION_BUCKET_MS,
    LOCAL_DEDUPE_METADATA_DURATION_TOLERANCE_MS,
    LOCAL_DEDUPE_SIMILAR_FINGERPRINT_THRESHOLD,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
    LOCAL_DEDUPE_SOURCE_ISRC,
    LOCAL_DEDUPE_SOURCE_METADATA,
    LocalDedupeDecisionRecord,
    LocalDedupeGroupRecord,
    LocalDedupeTrackRecord,
    local_dedupe_decisions_table,
)
from app.local_tracks.store import local_tracks_table
from app.m3u.jobs import affected_full_sync_playlist_ids_for_streaming_tracks
from app.matching.pipeline import SUGGESTED_LINK_STATUS_PENDING, suggested_links_table
from app.sonic.models import (
    generated_playlist_tracks_table,
    sonic_track_features_table,
)
from app.soulseek.models import soulseek_acquisitions_table


DEFAULT_LOCAL_DEDUPE_QUARANTINE_ROOT = "/nas/cratelynx/dedupe-quarantine"


class LocalDedupeGroupNotFoundError(ValueError):
    pass


class LocalDedupeInvalidKeeperError(ValueError):
    pass


class LocalDedupeFileNotFoundError(FileNotFoundError):
    pass


class LocalDedupeUnsafePathError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalDedupeResolveResult:
    affected_playlist_ids: tuple[int, ...]
    decision: LocalDedupeDecisionRecord


@dataclass(frozen=True, slots=True)
class _MovedFile:
    original_path: Path
    quarantine_path: Path


class LocalDedupeStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_groups(self) -> list[LocalDedupeGroupRecord]:
        tracks = self._list_tracks()
        groups = _dedupe_groups(
            [
                *_fingerprint_exact_groups(tracks),
                *_fingerprint_similar_groups(tracks),
                *_isrc_groups(tracks),
                *_metadata_groups(tracks),
            ]
        )
        dismissed_or_resolved_keys = self._decision_group_keys()
        return [
            group
            for group in groups
            if group.group_key not in dismissed_or_resolved_keys
        ]

    def dismiss_group(self, group_key: str) -> LocalDedupeDecisionRecord:
        group = self._group_by_key(group_key)
        if group is None:
            raise LocalDedupeGroupNotFoundError(group_key)

        with self._engine.begin() as connection:
            decision_id = _insert_decision(
                connection,
                action=LOCAL_DEDUPE_ACTION_DISMISSED,
                group=group,
                keeper_local_track_id=None,
                quarantine_paths=[],
                quarantined_local_track_ids=[],
            )
            row = (
                connection.execute(
                    select(local_dedupe_decisions_table).where(
                        local_dedupe_decisions_table.c.id == decision_id
                    )
                )
                .mappings()
                .one()
            )
        return _decision_from_row(row)

    def resolve_group(
        self,
        *,
        group_key: str,
        keeper_local_track_id: int,
        beets_library: Path | str | None = None,
        library_root: Path | str | None = None,
        quarantine_root: Path | str | None = None,
    ) -> LocalDedupeResolveResult:
        group = self._group_by_key(group_key)
        if group is None:
            raise LocalDedupeGroupNotFoundError(group_key)

        track_ids = {track.id for track in group.tracks}
        if keeper_local_track_id not in track_ids:
            raise LocalDedupeInvalidKeeperError(str(keeper_local_track_id))

        duplicate_tracks = [
            track for track in group.tracks if track.id != keeper_local_track_id
        ]
        resolved_library_root = Path(
            library_root or os.environ.get("LIBRARY_ROOT", "/nas/media/music")
        ).resolve()
        resolved_quarantine_root = Path(
            quarantine_root
            or os.environ.get(
                "LOCAL_DEDUPE_QUARANTINE_ROOT",
                DEFAULT_LOCAL_DEDUPE_QUARANTINE_ROOT,
            )
        ).resolve()
        moved_files = _quarantine_files(
            duplicate_tracks,
            library_root=resolved_library_root,
            quarantine_root=resolved_quarantine_root,
        )

        try:
            with self._engine.begin() as connection:
                duplicate_ids = tuple(track.id for track in duplicate_tracks)
                duplicate_beets_ids = tuple(
                    track.beets_id
                    for track in duplicate_tracks
                    if track.beets_id is not None
                )
                duplicate_final_link_rows = (
                    connection.execute(
                        select(
                            final_links_table.c.id,
                            final_links_table.c.streaming_track_id,
                        ).where(final_links_table.c.local_track_id.in_(duplicate_ids))
                    )
                    .mappings()
                    .all()
                )
                duplicate_final_link_ids = tuple(
                    int(row["id"]) for row in duplicate_final_link_rows
                )
                affected_streaming_track_ids = {
                    int(row["streaming_track_id"]) for row in duplicate_final_link_rows
                }
                affected_playlist_ids = (
                    affected_full_sync_playlist_ids_for_streaming_tracks(
                        connection,
                        affected_streaming_track_ids,
                    )
                    if affected_streaming_track_ids
                    else ()
                )

                _delete_duplicate_track_references(
                    connection,
                    duplicate_ids=duplicate_ids,
                    duplicate_beets_ids=duplicate_beets_ids,
                    duplicate_final_link_ids=duplicate_final_link_ids,
                )
                decision_id = _insert_decision(
                    connection,
                    action=LOCAL_DEDUPE_ACTION_RESOLVED,
                    group=group,
                    keeper_local_track_id=keeper_local_track_id,
                    quarantine_paths=[
                        str(moved_file.quarantine_path) for moved_file in moved_files
                    ],
                    quarantined_local_track_ids=list(duplicate_ids),
                )
                _delete_beets_sqlite_items(
                    tuple(int(beets_id) for beets_id in duplicate_beets_ids),
                    beets_library=Path(
                        beets_library
                        or os.environ.get("BEETS_LIBRARY", "/data/beets/library.db")
                    ),
                )
                row = (
                    connection.execute(
                        select(local_dedupe_decisions_table).where(
                            local_dedupe_decisions_table.c.id == decision_id
                        )
                    )
                    .mappings()
                    .one()
                )
        except Exception:
            _restore_moved_files(moved_files)
            raise

        return LocalDedupeResolveResult(
            affected_playlist_ids=tuple(int(value) for value in affected_playlist_ids),
            decision=_decision_from_row(row),
        )

    def _group_by_key(self, group_key: str) -> LocalDedupeGroupRecord | None:
        return next(
            (group for group in self.list_groups() if group.group_key == group_key),
            None,
        )

    def _decision_group_keys(self) -> set[str]:
        with self._engine.connect() as connection:
            return set(
                str(group_key)
                for group_key in connection.execute(
                    select(local_dedupe_decisions_table.c.group_key)
                ).scalars()
            )

    def _list_tracks(self) -> list[LocalDedupeTrackRecord]:
        pending_suggestion_ids = (
            select(
                suggested_links_table.c.local_track_id,
                func.min(suggested_links_table.c.id).label("suggestion_id"),
            )
            .where(suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING)
            .group_by(suggested_links_table.c.local_track_id)
            .subquery()
        )
        query = (
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                local_tracks_table.c.fingerprint,
                local_tracks_table.c.beets_id,
                final_links_table.c.id.label("final_link_id"),
                pending_suggestion_ids.c.suggestion_id,
                beets_items_table.c.title,
                beets_items_table.c.artist,
                beets_items_table.c.album,
                beets_items_table.c.length,
                beets_items_table.c.isrc,
                beets_items_table.c["format"].label("format"),
                beets_items_table.c.bitrate,
                beets_items_table.c.samplerate,
                beets_items_table.c.bitdepth,
            )
            .select_from(
                local_tracks_table.outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
                .outerjoin(
                    final_links_table,
                    final_links_table.c.local_track_id == local_tracks_table.c.id,
                )
                .outerjoin(
                    pending_suggestion_ids,
                    pending_suggestion_ids.c.local_track_id == local_tracks_table.c.id,
                )
            )
            .order_by(local_tracks_table.c.id.asc())
        )

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()

        return [
            LocalDedupeTrackRecord(
                id=int(row["id"]),
                album=_str_or_none(row["album"]),
                artist=_str_or_none(row["artist"]),
                beets_id=_int_or_none(row["beets_id"]),
                bitdepth=_int_or_none(row["bitdepth"]),
                bitrate=_int_or_none(row["bitrate"]),
                duration_ms=_duration_ms(row["length"]),
                file_path=str(row["file_path"]),
                final_link_id=_int_or_none(row["final_link_id"]),
                fingerprint=_str_or_none(row["fingerprint"]),
                format=_str_or_none(row["format"]),
                isrc=normalize_isrc_code(row["isrc"]),
                library_root_rel_path=str(row["library_root_rel_path"]),
                link_status=_link_status(row),
                samplerate=_int_or_none(row["samplerate"]),
                title=_str_or_none(row["title"]),
            )
            for row in rows
        ]


def _fingerprint_exact_groups(
    tracks: list[LocalDedupeTrackRecord],
) -> list[LocalDedupeGroupRecord]:
    tracks_by_fingerprint: dict[str, list[LocalDedupeTrackRecord]] = defaultdict(list)
    for track in tracks:
        if track.fingerprint:
            tracks_by_fingerprint[track.fingerprint].append(track)

    return [
        _group(
            source=LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
            source_value=fingerprint,
            match_score=1.0,
            tracks=group_tracks,
        )
        for fingerprint, group_tracks in tracks_by_fingerprint.items()
        if len(group_tracks) > 1
    ]


def _fingerprint_similar_groups(
    tracks: list[LocalDedupeTrackRecord],
    *,
    threshold: float = LOCAL_DEDUPE_SIMILAR_FINGERPRINT_THRESHOLD,
) -> list[LocalDedupeGroupRecord]:
    comparable_tracks = [
        track for track in tracks if track.fingerprint and track.duration_ms is not None
    ]
    if len(comparable_tracks) < 2:
        return []

    by_bucket: dict[int, list[LocalDedupeTrackRecord]] = defaultdict(list)
    for track in comparable_tracks:
        by_bucket[track.duration_ms // LOCAL_DEDUPE_DURATION_BUCKET_MS].append(track)

    union_find = _UnionFind(track.id for track in comparable_tracks)
    edge_scores: dict[tuple[int, int], float] = {}
    compared_pairs: set[tuple[int, int]] = set()
    for bucket, bucket_tracks in by_bucket.items():
        candidate_tracks = [
            *bucket_tracks,
            *by_bucket.get(bucket + 1, []),
        ]
        for index, left in enumerate(bucket_tracks):
            for right in candidate_tracks[index + 1 :]:
                pair_key = tuple(sorted((left.id, right.id)))
                if pair_key in compared_pairs:
                    continue
                compared_pairs.add(pair_key)
                if left.fingerprint == right.fingerprint:
                    continue
                if (
                    abs(left.duration_ms - right.duration_ms)
                    > LOCAL_DEDUPE_METADATA_DURATION_TOLERANCE_MS
                ):
                    continue
                score = _compare_chromaprint_fingerprints(
                    left.fingerprint or "",
                    right.fingerprint or "",
                )
                if score is None or score < threshold:
                    continue
                union_find.union(left.id, right.id)
                edge_scores[pair_key] = score

    tracks_by_id = {track.id: track for track in comparable_tracks}
    groups = []
    for ids in union_find.groups():
        if len(ids) < 2:
            continue
        group_tracks = [tracks_by_id[track_id] for track_id in sorted(ids)]
        pair_scores = [
            score
            for pair, score in edge_scores.items()
            if pair[0] in ids and pair[1] in ids
        ]
        groups.append(
            _group(
                source=LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
                source_value=",".join(str(track_id) for track_id in sorted(ids)),
                match_score=max(pair_scores or [threshold]),
                tracks=group_tracks,
            )
        )
    return groups


def _isrc_groups(
    tracks: list[LocalDedupeTrackRecord],
) -> list[LocalDedupeGroupRecord]:
    tracks_by_isrc: dict[str, list[LocalDedupeTrackRecord]] = defaultdict(list)
    for track in tracks:
        if track.isrc:
            tracks_by_isrc[track.isrc].append(track)

    return [
        _group(
            source=LOCAL_DEDUPE_SOURCE_ISRC,
            source_value=isrc,
            match_score=0.95,
            tracks=group_tracks,
        )
        for isrc, group_tracks in tracks_by_isrc.items()
        if len(group_tracks) > 1
    ]


def _metadata_groups(
    tracks: list[LocalDedupeTrackRecord],
) -> list[LocalDedupeGroupRecord]:
    tracks_by_key: dict[str, list[LocalDedupeTrackRecord]] = defaultdict(list)
    for track in tracks:
        key = _metadata_key(track)
        if key is not None:
            tracks_by_key[key].append(track)

    groups: list[LocalDedupeGroupRecord] = []
    for key, keyed_tracks in tracks_by_key.items():
        if len(keyed_tracks) < 2:
            continue
        union_find = _UnionFind(track.id for track in keyed_tracks)
        for index, left in enumerate(keyed_tracks):
            for right in keyed_tracks[index + 1 :]:
                if _metadata_tracks_match(left, right):
                    union_find.union(left.id, right.id)
        tracks_by_id = {track.id: track for track in keyed_tracks}
        for ids in union_find.groups():
            if len(ids) < 2:
                continue
            group_tracks = [tracks_by_id[track_id] for track_id in sorted(ids)]
            groups.append(
                _group(
                    source=LOCAL_DEDUPE_SOURCE_METADATA,
                    source_value=key,
                    match_score=0.72,
                    tracks=group_tracks,
                )
            )
    return groups


def _dedupe_groups(
    groups: list[LocalDedupeGroupRecord],
) -> list[LocalDedupeGroupRecord]:
    source_rank = {
        LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT: 0,
        LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR: 1,
        LOCAL_DEDUPE_SOURCE_ISRC: 2,
        LOCAL_DEDUPE_SOURCE_METADATA: 3,
    }
    sorted_groups = sorted(
        groups,
        key=lambda group: (
            source_rank[group.source],
            -group.match_score,
            [track.id for track in group.tracks],
        ),
    )
    by_track_set: dict[tuple[int, ...], LocalDedupeGroupRecord] = {}
    for group in sorted_groups:
        key = tuple(track.id for track in group.tracks)
        by_track_set.setdefault(key, group)
    return sorted(
        by_track_set.values(),
        key=lambda group: (
            source_rank[group.source],
            -group.match_score,
            [track.id for track in group.tracks],
        ),
    )


def _group(
    *,
    source: str,
    source_value: str,
    match_score: float,
    tracks: list[LocalDedupeTrackRecord],
) -> LocalDedupeGroupRecord:
    sorted_tracks = sorted(tracks, key=lambda track: track.id)
    track_ids = ",".join(str(track.id) for track in sorted_tracks)
    digest = hashlib.sha256(f"{source}|{source_value}|{track_ids}".encode()).hexdigest()
    return LocalDedupeGroupRecord(
        group_key=f"{source}:{digest[:24]}",
        source=source,
        match_score=max(0.0, min(1.0, match_score)),
        tracks=sorted_tracks,
    )


def _quarantine_files(
    tracks: Iterable[LocalDedupeTrackRecord],
    *,
    library_root: Path,
    quarantine_root: Path,
) -> list[_MovedFile]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    moved_files: list[_MovedFile] = []
    try:
        for track in tracks:
            source_path = _resolve_library_file(track.file_path, library_root)
            if not source_path.is_file():
                raise LocalDedupeFileNotFoundError(str(source_path))
            quarantine_path = (
                quarantine_root
                / timestamp
                / f"local-{track.id}"
                / Path(track.library_root_rel_path)
            ).resolve()
            try:
                quarantine_path.relative_to(quarantine_root)
            except ValueError as exc:
                raise LocalDedupeUnsafePathError(str(quarantine_path)) from exc
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(quarantine_path))
            moved_files.append(
                _MovedFile(original_path=source_path, quarantine_path=quarantine_path)
            )
    except Exception:
        _restore_moved_files(moved_files)
        raise
    return moved_files


def _restore_moved_files(moved_files: Iterable[_MovedFile]) -> None:
    for moved_file in reversed(list(moved_files)):
        if not moved_file.quarantine_path.exists():
            continue
        moved_file.original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(moved_file.quarantine_path), str(moved_file.original_path))


def _resolve_library_file(file_path: str, library_root: Path) -> Path:
    candidate = (library_root / Path(file_path)).resolve()
    try:
        candidate.relative_to(library_root)
    except ValueError as exc:
        raise LocalDedupeUnsafePathError(file_path) from exc
    return candidate


def _delete_duplicate_track_references(
    connection,
    *,
    duplicate_ids: tuple[int, ...],
    duplicate_beets_ids: tuple[int, ...],
    duplicate_final_link_ids: tuple[int, ...],
) -> None:
    if not duplicate_ids:
        return

    if duplicate_final_link_ids:
        connection.execute(
            update(soulseek_acquisitions_table)
            .where(
                soulseek_acquisitions_table.c.final_link_id.in_(
                    duplicate_final_link_ids
                )
            )
            .values(final_link_id=None)
        )
    connection.execute(
        update(soulseek_acquisitions_table)
        .where(soulseek_acquisitions_table.c.local_track_id.in_(duplicate_ids))
        .values(local_track_id=None, final_link_id=None)
    )
    connection.execute(
        update(failed_ingestion_attempts_table)
        .where(failed_ingestion_attempts_table.c.local_track_id.in_(duplicate_ids))
        .values(local_track_id=None)
    )
    connection.execute(
        delete(generated_playlist_tracks_table).where(
            generated_playlist_tracks_table.c.local_track_id.in_(duplicate_ids)
        )
    )
    connection.execute(
        delete(sonic_track_features_table).where(
            sonic_track_features_table.c.local_track_id.in_(duplicate_ids)
        )
    )
    connection.execute(
        delete(suggested_links_table).where(
            suggested_links_table.c.local_track_id.in_(duplicate_ids)
        )
    )
    connection.execute(
        delete(final_links_table).where(
            final_links_table.c.local_track_id.in_(duplicate_ids)
        )
    )
    if duplicate_beets_ids:
        connection.execute(
            delete(beets_item_attributes_table).where(
                beets_item_attributes_table.c.entity_id.in_(duplicate_beets_ids)
            )
        )
        connection.execute(
            delete(beets_items_table).where(
                beets_items_table.c.beets_id.in_(duplicate_beets_ids)
            )
        )
    connection.execute(
        delete(local_tracks_table).where(local_tracks_table.c.id.in_(duplicate_ids))
    )


def _insert_decision(
    connection,
    *,
    action: str,
    group: LocalDedupeGroupRecord,
    keeper_local_track_id: int | None,
    quarantine_paths: list[str],
    quarantined_local_track_ids: list[int],
) -> int:
    result = connection.execute(
        insert(local_dedupe_decisions_table).values(
            group_key=group.group_key,
            action=action,
            source=group.source,
            match_score=group.match_score,
            keeper_local_track_id=keeper_local_track_id,
            track_ids_json=[track.id for track in group.tracks],
            quarantined_track_ids_json=quarantined_local_track_ids,
            quarantine_paths_json=quarantine_paths,
        )
    )
    decision_id = result.inserted_primary_key[0]
    if not isinstance(decision_id, int):
        raise ValueError("Failed to persist local dedupe decision")
    return decision_id


def _delete_beets_sqlite_items(
    beets_ids: tuple[int, ...],
    *,
    beets_library: Path,
) -> None:
    if not beets_ids or not beets_library.exists():
        return

    placeholders = ",".join("?" for _ in beets_ids)
    with sqlite3.connect(beets_library) as connection:
        connection.execute(
            f"DELETE FROM item_attributes WHERE entity_id IN ({placeholders})",
            beets_ids,
        )
        connection.execute(
            f"DELETE FROM items WHERE id IN ({placeholders})",
            beets_ids,
        )


def _compare_chromaprint_fingerprints(left: str, right: str) -> float | None:
    try:
        from acoustid import compare_fingerprints
    except ImportError:
        return None

    try:
        score = compare_fingerprints((0, left), (0, right))
    except Exception:
        return None

    return float(score)


def _decision_from_row(row) -> LocalDedupeDecisionRecord:
    return LocalDedupeDecisionRecord(
        action=str(row["action"]),
        created_at=row["created_at"],
        group_key=str(row["group_key"]),
        id=int(row["id"]),
        keeper_local_track_id=_int_or_none(row["keeper_local_track_id"]),
        match_score=(
            float(row["match_score"]) if row["match_score"] is not None else None
        ),
        quarantine_paths_json=row["quarantine_paths_json"],
        quarantined_track_ids_json=row["quarantined_track_ids_json"],
        source=str(row["source"]),
        track_ids_json=row["track_ids_json"],
    )


def _metadata_key(track: LocalDedupeTrackRecord) -> str | None:
    title = _normalize_text(track.title)
    artist = _normalize_text(track.artist)
    if title is None or artist is None:
        return None
    return f"{artist}|{title}"


def _metadata_tracks_match(
    left: LocalDedupeTrackRecord,
    right: LocalDedupeTrackRecord,
) -> bool:
    if left.duration_ms is None or right.duration_ms is None:
        return False
    return (
        abs(left.duration_ms - right.duration_ms)
        <= LOCAL_DEDUPE_METADATA_DURATION_TOLERANCE_MS
    )


def _normalize_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    return normalized or None


def _duration_ms(value: object) -> int | None:
    if value is None:
        return None
    return int(float(value) * 1000)


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int) else None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _link_status(row) -> str:
    if row["final_link_id"] is not None:
        return "linked"
    if row["suggestion_id"] is not None:
        return "pending"
    return "unlinked"


class _UnionFind:
    def __init__(self, values: Iterable[int]) -> None:
        self._parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root

    def groups(self) -> list[set[int]]:
        groups: dict[int, set[int]] = defaultdict(set)
        for value in self._parent:
            groups[self.find(value)].add(value)
        return list(groups.values())

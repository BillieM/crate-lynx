from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any, Literal, cast
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.m3u.generator import (
    DEFAULT_M3U_EXPORT_PATH_FORMAT,
    M3uExportPathFormat,
    M3uPlaylistExport,
    build_generated_m3u_playlist_export,
    build_m3u_playlist_export,
    format_export_audio_path,
    format_file_url,
    normalize_m3u_export_path_format,
)
from app.sonic.models import generated_playlists_table, playlist_generation_runs_table
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    YOUTUBE_MUSIC_PROVIDER,
    streaming_accounts_table,
    streaming_playlists_table,
)


M3uExportFormat = Literal["m3u", "m3u8"]
M3U_EXPORT_FORMAT_M3U: M3uExportFormat = "m3u"
M3U_EXPORT_FORMAT_M3U8: M3uExportFormat = "m3u8"
DEFAULT_M3U_EXPORT_FORMATS: tuple[M3uExportFormat, ...] = (
    M3U_EXPORT_FORMAT_M3U,
    M3U_EXPORT_FORMAT_M3U8,
)
SUPPORTED_M3U_EXPORT_FORMATS = frozenset(DEFAULT_M3U_EXPORT_FORMATS)
REKORDBOX_XML_STREAMING_ROOT = "YouTube Music"
REKORDBOX_XML_GENERATED_ROOT = "Generated Runs"


class InvalidM3uExportFormatError(ValueError):
    pass


class M3uExportPlaylistNotFoundError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class M3uExportPlaylist:
    playlist_id: int | None
    generated_playlist_id: int | None
    generated_run_id: int | None
    source: str
    title: str
    filename_m3u: str
    filename_m3u8: str
    archive_path_m3u: str
    archive_path_m3u8: str
    rendered: M3uPlaylistExport

    def filenames(self, formats: Iterable[M3uExportFormat]) -> list[str]:
        filenames = []
        for export_format in formats:
            if export_format == M3U_EXPORT_FORMAT_M3U:
                filenames.append(self.filename_m3u)
            elif export_format == M3U_EXPORT_FORMAT_M3U8:
                filenames.append(self.filename_m3u8)
        return filenames

    def archive_paths(self, formats: Iterable[M3uExportFormat]) -> list[str]:
        paths = []
        for export_format in formats:
            if export_format == M3U_EXPORT_FORMAT_M3U:
                paths.append(self.archive_path_m3u)
            elif export_format == M3U_EXPORT_FORMAT_M3U8:
                paths.append(self.archive_path_m3u8)
        return paths


@dataclass(frozen=True, slots=True)
class M3uExportPackage:
    library_path: str
    formats: tuple[M3uExportFormat, ...]
    path_format: M3uExportPathFormat
    playlists: list[M3uExportPlaylist]

    @property
    def total_exported_track_count(self) -> int:
        return sum(
            playlist.rendered.exported_track_count for playlist in self.playlists
        )

    @property
    def total_skipped_track_count(self) -> int:
        return sum(playlist.rendered.skipped_track_count for playlist in self.playlists)


def build_m3u_export_package(
    *,
    engine: Engine | None = None,
    formats: Iterable[str] = DEFAULT_M3U_EXPORT_FORMATS,
    generated_playlist_ids: list[int] | None = None,
    generated_run_ids: list[int] | None = None,
    library_path: str,
    path_format: str = DEFAULT_M3U_EXPORT_PATH_FORMAT,
    playlist_ids: list[int],
) -> M3uExportPackage:
    engine = engine or create_database_engine()
    export_formats = normalize_m3u_export_formats(formats)
    export_path_format = normalize_m3u_export_path_format(path_format)
    normalized_ids = _normalize_playlist_ids(playlist_ids)
    normalized_generated_ids = _normalize_playlist_ids(generated_playlist_ids or [])
    normalized_generated_run_ids = _normalize_playlist_ids(generated_run_ids or [])
    if (
        not normalized_ids
        and not normalized_generated_ids
        and not normalized_generated_run_ids
    ):
        return M3uExportPackage(
            library_path=library_path,
            formats=export_formats,
            path_format=export_path_format,
            playlists=[],
        )

    playlists: list[M3uExportPlaylist] = []
    filename_stem_inputs: list[tuple[str, str]] = []

    with engine.connect() as connection:
        streaming_rows = (
            connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.title,
                    streaming_accounts_table.c.provider,
                )
                .select_from(
                    streaming_playlists_table.join(
                        streaming_accounts_table,
                        streaming_accounts_table.c.id
                        == streaming_playlists_table.c.account_id,
                    )
                )
                .where(streaming_playlists_table.c.id.in_(normalized_ids))
                .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
            )
            .mappings()
            .all()
        )
        generated_rows = (
            connection.execute(
                select(
                    generated_playlists_table.c.id,
                    generated_playlists_table.c.name,
                    generated_playlists_table.c.run_id,
                ).where(generated_playlists_table.c.id.in_(normalized_generated_ids))
            )
            .mappings()
            .all()
            if normalized_generated_ids
            else []
        )
        generated_run_rows = (
            connection.execute(
                select(playlist_generation_runs_table.c.id).where(
                    playlist_generation_runs_table.c.id.in_(
                        normalized_generated_run_ids
                    )
                )
            )
            .mappings()
            .all()
            if normalized_generated_run_ids
            else []
        )
        generated_run_playlist_rows = (
            connection.execute(
                select(
                    generated_playlists_table.c.id,
                    generated_playlists_table.c.name,
                    generated_playlists_table.c.run_id,
                    generated_playlists_table.c.parent_playlist_id,
                    generated_playlists_table.c.depth,
                    generated_playlists_table.c.position,
                )
                .where(
                    generated_playlists_table.c.run_id.in_(normalized_generated_run_ids)
                )
                .order_by(
                    generated_playlists_table.c.run_id.asc(),
                    generated_playlists_table.c.depth.asc(),
                    generated_playlists_table.c.position.asc(),
                    generated_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .all()
            if normalized_generated_run_ids
            else []
        )

    rows_by_id = {int(row["id"]): row for row in streaming_rows}
    missing_ids = [
        playlist_id for playlist_id in normalized_ids if playlist_id not in rows_by_id
    ]
    if missing_ids:
        raise M3uExportPlaylistNotFoundError(
            f"Full-sync playlist not found: {missing_ids[0]}"
        )

    generated_rows_by_id = {int(row["id"]): row for row in generated_rows}
    missing_generated_ids = [
        playlist_id
        for playlist_id in normalized_generated_ids
        if playlist_id not in generated_rows_by_id
    ]
    if missing_generated_ids:
        raise M3uExportPlaylistNotFoundError(
            f"Generated playlist not found: {missing_generated_ids[0]}"
        )

    generated_run_ids_by_id = {int(row["id"]) for row in generated_run_rows}
    missing_generated_run_ids = [
        run_id
        for run_id in normalized_generated_run_ids
        if run_id not in generated_run_ids_by_id
    ]
    if missing_generated_run_ids:
        raise M3uExportPlaylistNotFoundError(
            f"Generated run not found: {missing_generated_run_ids[0]}"
        )

    for playlist_id in normalized_ids:
        filename_stem_inputs.append(
            (
                rows_by_id[playlist_id]["title"],
                _provider_suffix(rows_by_id[playlist_id]["provider"]),
            )
        )
    for playlist_id in normalized_generated_ids:
        filename_stem_inputs.append((generated_rows_by_id[playlist_id]["name"], "gen"))

    filename_stems = _dedupe_filename_stems(
        [
            build_m3u_export_filename_stem(title, provider_suffix)
            for title, provider_suffix in filename_stem_inputs
        ]
    )

    filename_index = 0
    for playlist_id in normalized_ids:
        filename_stem = filename_stems[filename_index]
        filename_index += 1
        row = rows_by_id[playlist_id]
        playlists.append(
            M3uExportPlaylist(
                playlist_id=playlist_id,
                generated_playlist_id=None,
                generated_run_id=None,
                source="streaming",
                title=row["title"],
                filename_m3u=f"{filename_stem}.m3u",
                filename_m3u8=f"{filename_stem}.m3u8",
                archive_path_m3u=f"{filename_stem}.m3u",
                archive_path_m3u8=f"{filename_stem}.m3u8",
                rendered=build_m3u_playlist_export(
                    playlist_id,
                    library_path,
                    include_extinf=False,
                    path_format=export_path_format,
                    engine=engine,
                ),
            )
        )
    for playlist_id in normalized_generated_ids:
        filename_stem = filename_stems[filename_index]
        filename_index += 1
        row = generated_rows_by_id[playlist_id]
        playlists.append(
            M3uExportPlaylist(
                playlist_id=None,
                generated_playlist_id=playlist_id,
                generated_run_id=int(row["run_id"]),
                source="generated",
                title=row["name"],
                filename_m3u=f"{filename_stem}.m3u",
                filename_m3u8=f"{filename_stem}.m3u8",
                archive_path_m3u=f"{filename_stem}.m3u",
                archive_path_m3u8=f"{filename_stem}.m3u8",
                rendered=build_generated_m3u_playlist_export(
                    playlist_id,
                    library_path,
                    include_extinf=False,
                    path_format=export_path_format,
                    engine=engine,
                ),
            )
        )

    generated_run_rows_by_id: dict[int, list[Any]] = {}
    for row in generated_run_playlist_rows:
        generated_run_rows_by_id.setdefault(int(row["run_id"]), []).append(row)

    for run_id in normalized_generated_run_ids:
        for row, path_stem in _generated_run_archive_path_stems(
            generated_run_rows_by_id.get(run_id, [])
        ):
            filename_stem = path_stem[-1]
            archive_path_stem = "/".join((f"Generated Run {run_id}", *path_stem))
            generated_playlist_id = int(row["id"])
            playlists.append(
                M3uExportPlaylist(
                    playlist_id=None,
                    generated_playlist_id=generated_playlist_id,
                    generated_run_id=run_id,
                    source="generated",
                    title=row["name"],
                    filename_m3u=f"{filename_stem}.m3u",
                    filename_m3u8=f"{filename_stem}.m3u8",
                    archive_path_m3u=f"{archive_path_stem}.m3u",
                    archive_path_m3u8=f"{archive_path_stem}.m3u8",
                    rendered=build_generated_m3u_playlist_export(
                        generated_playlist_id,
                        library_path,
                        include_extinf=False,
                        path_format=export_path_format,
                        engine=engine,
                    ),
                )
            )

    return M3uExportPackage(
        library_path=library_path,
        formats=export_formats,
        path_format=export_path_format,
        playlists=playlists,
    )


def build_full_rekordbox_xml_export_package(
    *,
    engine: Engine | None = None,
    library_path: str,
    path_format: str = DEFAULT_M3U_EXPORT_PATH_FORMAT,
) -> M3uExportPackage:
    engine = engine or create_database_engine()
    export_path_format = normalize_m3u_export_path_format(path_format)
    playlists: list[M3uExportPlaylist] = []

    with engine.connect() as connection:
        streaming_rows = (
            connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.title,
                    streaming_accounts_table.c.provider,
                )
                .select_from(
                    streaming_playlists_table.join(
                        streaming_accounts_table,
                        streaming_accounts_table.c.id
                        == streaming_playlists_table.c.account_id,
                    )
                )
                .where(streaming_accounts_table.c.provider == YOUTUBE_MUSIC_PROVIDER)
                .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
                .order_by(
                    streaming_playlists_table.c.title.asc(),
                    streaming_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .all()
        )
        generated_run_rows = (
            connection.execute(
                select(playlist_generation_runs_table.c.id).order_by(
                    playlist_generation_runs_table.c.id.asc()
                )
            )
            .mappings()
            .all()
        )
        generated_run_ids = [int(row["id"]) for row in generated_run_rows]
        generated_run_playlist_rows = (
            connection.execute(
                select(
                    generated_playlists_table.c.id,
                    generated_playlists_table.c.name,
                    generated_playlists_table.c.run_id,
                    generated_playlists_table.c.parent_playlist_id,
                    generated_playlists_table.c.depth,
                    generated_playlists_table.c.position,
                )
                .where(generated_playlists_table.c.run_id.in_(generated_run_ids))
                .order_by(
                    generated_playlists_table.c.run_id.asc(),
                    generated_playlists_table.c.depth.asc(),
                    generated_playlists_table.c.position.asc(),
                    generated_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .all()
            if generated_run_ids
            else []
        )

    streaming_filename_stems = _dedupe_filename_stems(
        [
            build_m3u_export_filename_stem(
                row["title"], _provider_suffix(row["provider"])
            )
            for row in streaming_rows
        ]
    )
    for row, filename_stem in zip(
        streaming_rows, streaming_filename_stems, strict=True
    ):
        playlist_id = int(row["id"])
        playlists.append(
            M3uExportPlaylist(
                playlist_id=playlist_id,
                generated_playlist_id=None,
                generated_run_id=None,
                source="streaming",
                title=row["title"],
                filename_m3u=f"{filename_stem}.m3u",
                filename_m3u8=f"{filename_stem}.m3u8",
                archive_path_m3u=f"{REKORDBOX_XML_STREAMING_ROOT}/{filename_stem}.m3u",
                archive_path_m3u8=f"{REKORDBOX_XML_STREAMING_ROOT}/{filename_stem}.m3u8",
                rendered=build_m3u_playlist_export(
                    playlist_id,
                    library_path,
                    include_extinf=False,
                    path_format=export_path_format,
                    engine=engine,
                ),
            )
        )

    generated_run_rows_by_id: dict[int, list[Any]] = {}
    for row in generated_run_playlist_rows:
        generated_run_rows_by_id.setdefault(int(row["run_id"]), []).append(row)

    for run_id in generated_run_ids:
        for row, path_stem in _generated_run_archive_path_stems(
            generated_run_rows_by_id.get(run_id, [])
        ):
            filename_stem = path_stem[-1]
            archive_path_stem = "/".join(
                (
                    REKORDBOX_XML_GENERATED_ROOT,
                    f"Generated Run {run_id}",
                    *path_stem,
                )
            )
            generated_playlist_id = int(row["id"])
            playlists.append(
                M3uExportPlaylist(
                    playlist_id=None,
                    generated_playlist_id=generated_playlist_id,
                    generated_run_id=run_id,
                    source="generated",
                    title=row["name"],
                    filename_m3u=f"{filename_stem}.m3u",
                    filename_m3u8=f"{filename_stem}.m3u8",
                    archive_path_m3u=f"{archive_path_stem}.m3u",
                    archive_path_m3u8=f"{archive_path_stem}.m3u8",
                    rendered=build_generated_m3u_playlist_export(
                        generated_playlist_id,
                        library_path,
                        include_extinf=False,
                        path_format=export_path_format,
                        engine=engine,
                    ),
                )
            )

    return M3uExportPackage(
        library_path=library_path,
        formats=DEFAULT_M3U_EXPORT_FORMATS,
        path_format=export_path_format,
        playlists=playlists,
    )


def build_m3u_export_zip(export_package: M3uExportPackage) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for playlist in export_package.playlists:
            content = playlist.rendered.content.encode("utf-8")
            for archive_path in playlist.archive_paths(export_package.formats):
                zip_file.writestr(archive_path, content)

    return archive.getvalue()


def build_rekordbox_xml(export_package: M3uExportPackage) -> str:
    track_ids_by_location: dict[str, int] = {}
    track_entries = []
    for playlist in export_package.playlists:
        for entry in playlist.rendered.entries:
            location = _rekordbox_track_location(
                export_package.library_path, entry.local_path
            )
            if location in track_ids_by_location:
                continue

            track_ids_by_location[location] = len(track_ids_by_location) + 1
            track_entries.append((track_ids_by_location[location], entry, location))

    root = ElementTree.Element("DJ_PLAYLISTS", {"Version": "1.0.0"})
    ElementTree.SubElement(
        root,
        "PRODUCT",
        {
            "Company": "crate-lynx",
            "Name": "crate-lynx",
            "Version": "1.0.0",
        },
    )
    collection = ElementTree.SubElement(
        root,
        "COLLECTION",
        {"Entries": str(len(track_entries))},
    )
    for track_id, entry, location in track_entries:
        ElementTree.SubElement(
            collection,
            "TRACK",
            {
                "Album": entry.album or "",
                "Artist": entry.artist,
                "AverageBpm": "0.00",
                "BitRate": "0",
                "Comments": "",
                "Composer": "",
                "DateAdded": "1970-01-01",
                "DiscNumber": "0",
                "Genre": "",
                "Grouping": "",
                "Kind": _rekordbox_track_kind(entry.local_path),
                "Label": "",
                "Location": location,
                "Mix": "",
                "Name": entry.title,
                "PlayCount": "0",
                "Rating": "0",
                "Remixer": "",
                "SampleRate": "0",
                "Size": "0",
                "Tonality": "",
                "TotalTime": str(_duration_seconds(entry.duration_ms)),
                "TrackID": str(track_id),
                "TrackNumber": "0",
                "Year": "0",
            },
        )

    playlists = ElementTree.SubElement(root, "PLAYLISTS")
    root_node = ElementTree.SubElement(
        playlists,
        "NODE",
        {"Count": "0", "Name": "ROOT", "Type": "0"},
    )
    playlist_by_path, folder_paths, order_by_path = _build_rekordbox_playlist_tree(
        export_package.playlists
    )
    root_node.set(
        "Count",
        str(
            _append_rekordbox_playlist_children(
                root_node,
                (),
                playlist_by_path=playlist_by_path,
                folder_paths=folder_paths,
                order_by_path=order_by_path,
                track_ids_by_location=track_ids_by_location,
                library_path=export_package.library_path,
            )
        ),
    )

    ElementTree.indent(root, space="\t")
    return ElementTree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    ).decode("utf-8")


def normalize_m3u_export_formats(
    formats: Iterable[str],
) -> tuple[M3uExportFormat, ...]:
    normalized_formats = []
    seen_formats: set[str] = set()
    for export_format in formats:
        if export_format not in SUPPORTED_M3U_EXPORT_FORMATS:
            raise InvalidM3uExportFormatError(
                f"Unsupported M3U export format: {export_format}"
            )
        if export_format not in seen_formats:
            seen_formats.add(export_format)
            normalized_formats.append(cast(M3uExportFormat, export_format))

    if not normalized_formats:
        raise InvalidM3uExportFormatError("At least one M3U export format is required")

    return tuple(normalized_formats)


def build_m3u_export_filename_stem(title: str, provider_suffix: str) -> str:
    sanitized = re.sub(
        r"[^A-Za-z0-9._ \[\]-]+",
        "-",
        f"{title} [{provider_suffix}]",
    ).strip(" -")
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or f"playlist [{provider_suffix}]"


def _normalize_playlist_ids(playlist_ids: list[int]) -> list[int]:
    normalized_ids = []
    seen_ids: set[int] = set()
    for playlist_id in playlist_ids:
        normalized_id = int(playlist_id)
        if normalized_id not in seen_ids:
            seen_ids.add(normalized_id)
            normalized_ids.append(normalized_id)
    return normalized_ids


def _dedupe_filename_stems(filename_stems: list[str]) -> list[str]:
    used_counts: dict[str, int] = {}
    deduped_stems = []
    for filename_stem in filename_stems:
        comparison_key = filename_stem.lower()
        used_counts[comparison_key] = used_counts.get(comparison_key, 0) + 1
        suffix = used_counts[comparison_key]
        if suffix == 1:
            deduped_stems.append(filename_stem)
        else:
            deduped_stems.append(f"{filename_stem}-{suffix}")
    return deduped_stems


def _generated_run_archive_path_stems(
    rows: list[Any],
) -> list[tuple[Any, tuple[str, ...]]]:
    rows_by_id = {int(row["id"]): row for row in rows}
    children_by_parent: dict[int | None, list[Any]] = {}
    for row in rows:
        parent_id = row["parent_playlist_id"]
        normalized_parent_id = int(parent_id) if parent_id in rows_by_id else None
        children_by_parent.setdefault(normalized_parent_id, []).append(row)

    ordered: list[tuple[Any, tuple[str, ...]]] = []
    visited_ids: set[int] = set()

    def append_children(parent_id: int | None, ancestors: tuple[str, ...]) -> None:
        children = sorted(
            children_by_parent.get(parent_id, []),
            key=lambda row: (int(row["position"]), int(row["id"])),
        )
        child_stems = _dedupe_filename_stems(
            [build_m3u_export_filename_stem(row["name"], "gen") for row in children]
        )
        for row, stem in zip(children, child_stems, strict=True):
            row_id = int(row["id"])
            if row_id in visited_ids:
                continue
            visited_ids.add(row_id)
            path_stem = (*ancestors, stem)
            ordered.append((row, path_stem))
            append_children(row_id, path_stem)

    append_children(None, ())
    return ordered


def _build_rekordbox_playlist_tree(
    playlists: list[M3uExportPlaylist],
) -> tuple[
    dict[tuple[str, ...], M3uExportPlaylist],
    set[tuple[str, ...]],
    dict[tuple[str, ...], int],
]:
    playlist_by_path: dict[tuple[str, ...], M3uExportPlaylist] = {}
    folder_paths: set[tuple[str, ...]] = set()
    order_by_path: dict[tuple[str, ...], int] = {}

    for index, playlist in enumerate(playlists):
        path = _rekordbox_playlist_path(playlist)
        playlist_by_path[path] = playlist
        for prefix_length in range(1, len(path) + 1):
            order_by_path.setdefault(path[:prefix_length], index)
        for prefix_length in range(1, len(path)):
            folder_paths.add(path[:prefix_length])

    return playlist_by_path, folder_paths, order_by_path


def _append_rekordbox_playlist_children(
    parent_node: ElementTree.Element,
    parent_path: tuple[str, ...],
    *,
    playlist_by_path: dict[tuple[str, ...], M3uExportPlaylist],
    folder_paths: set[tuple[str, ...]],
    order_by_path: dict[tuple[str, ...], int],
    track_ids_by_location: dict[str, int],
    library_path: str,
) -> int:
    child_paths = []
    all_paths = set(playlist_by_path) | folder_paths
    for path in all_paths:
        if (
            len(path) == len(parent_path) + 1
            and path[: len(parent_path)] == parent_path
        ):
            child_paths.append(path)

    child_paths.sort(
        key=lambda path: (
            order_by_path.get(path, len(order_by_path)),
            path[-1].lower(),
        )
    )

    direct_child_count = 0
    for child_path in child_paths:
        if child_path in folder_paths:
            folder_node = ElementTree.SubElement(
                parent_node,
                "NODE",
                {"Count": "0", "Name": child_path[-1], "Type": "0"},
            )
            folder_child_count = 0
            if child_path in playlist_by_path:
                _append_rekordbox_playlist_node(
                    folder_node,
                    playlist_by_path[child_path],
                    name=child_path[-1],
                    track_ids_by_location=track_ids_by_location,
                    library_path=library_path,
                )
                folder_child_count += 1
            folder_child_count += _append_rekordbox_playlist_children(
                folder_node,
                child_path,
                playlist_by_path=playlist_by_path,
                folder_paths=folder_paths,
                order_by_path=order_by_path,
                track_ids_by_location=track_ids_by_location,
                library_path=library_path,
            )
            folder_node.set("Count", str(folder_child_count))
        else:
            _append_rekordbox_playlist_node(
                parent_node,
                playlist_by_path[child_path],
                name=child_path[-1],
                track_ids_by_location=track_ids_by_location,
                library_path=library_path,
            )
        direct_child_count += 1

    return direct_child_count


def _append_rekordbox_playlist_node(
    parent_node: ElementTree.Element,
    playlist: M3uExportPlaylist,
    *,
    name: str,
    track_ids_by_location: dict[str, int],
    library_path: str,
) -> None:
    playlist_node = ElementTree.SubElement(
        parent_node,
        "NODE",
        {
            "Entries": str(len(playlist.rendered.entries)),
            "KeyType": "0",
            "Name": name,
            "Type": "1",
        },
    )
    for entry in playlist.rendered.entries:
        location = _rekordbox_track_location(library_path, entry.local_path)
        ElementTree.SubElement(
            playlist_node,
            "TRACK",
            {"Key": str(track_ids_by_location[location])},
        )


def _rekordbox_playlist_path(playlist: M3uExportPlaylist) -> tuple[str, ...]:
    path = playlist.archive_path_m3u.removesuffix(".m3u")
    return tuple(part for part in path.split("/") if part)


def _rekordbox_track_location(library_path: str, local_path: str) -> str:
    return format_file_url(format_export_audio_path(library_path, local_path))


def _rekordbox_track_kind(local_path: str) -> str:
    normalized_path = local_path.replace("\\", "/")
    filename = normalized_path.rsplit("/", 1)[-1]
    if "." not in filename:
        return "Audio File"

    extension = filename.rsplit(".", 1)[-1].upper()
    return f"{extension} File" if extension else "Audio File"


def _duration_seconds(duration_ms: int | None) -> int:
    if duration_ms is None:
        return 0

    return duration_ms // 1000


def _provider_suffix(provider: str) -> str:
    if provider == YOUTUBE_MUSIC_PROVIDER:
        return "yt"

    return re.sub(r"[^A-Za-z0-9]+", "-", provider).strip("-").lower() or "streaming"

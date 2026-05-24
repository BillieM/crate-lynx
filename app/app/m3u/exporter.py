from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
import re
from typing import Literal, cast
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.m3u.generator import (
    DEFAULT_M3U_EXPORT_PATH_FORMAT,
    M3uExportPathFormat,
    M3uPlaylistExport,
    build_m3u_playlist_export,
    normalize_m3u_export_path_format,
)
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


class InvalidM3uExportFormatError(ValueError):
    pass


class M3uExportPlaylistNotFoundError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class M3uExportPlaylist:
    playlist_id: int
    title: str
    filename_m3u: str
    filename_m3u8: str
    rendered: M3uPlaylistExport

    def filenames(self, formats: Iterable[M3uExportFormat]) -> list[str]:
        filenames = []
        for export_format in formats:
            if export_format == M3U_EXPORT_FORMAT_M3U:
                filenames.append(self.filename_m3u)
            elif export_format == M3U_EXPORT_FORMAT_M3U8:
                filenames.append(self.filename_m3u8)
        return filenames


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
    library_path: str,
    path_format: str = DEFAULT_M3U_EXPORT_PATH_FORMAT,
    playlist_ids: list[int],
) -> M3uExportPackage:
    engine = engine or create_database_engine()
    export_formats = normalize_m3u_export_formats(formats)
    export_path_format = normalize_m3u_export_path_format(path_format)
    normalized_ids = _normalize_playlist_ids(playlist_ids)
    if not normalized_ids:
        return M3uExportPackage(
            library_path=library_path,
            formats=export_formats,
            path_format=export_path_format,
            playlists=[],
        )

    with engine.connect() as connection:
        rows = (
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

    rows_by_id = {int(row["id"]): row for row in rows}
    missing_ids = [
        playlist_id for playlist_id in normalized_ids if playlist_id not in rows_by_id
    ]
    if missing_ids:
        raise M3uExportPlaylistNotFoundError(
            f"Full-sync playlist not found: {missing_ids[0]}"
        )

    filename_stems = _dedupe_filename_stems(
        [
            build_m3u_export_filename_stem(
                rows_by_id[playlist_id]["title"],
                _provider_suffix(rows_by_id[playlist_id]["provider"]),
            )
            for playlist_id in normalized_ids
        ]
    )

    playlists = []
    for playlist_id, filename_stem in zip(normalized_ids, filename_stems, strict=True):
        row = rows_by_id[playlist_id]
        playlists.append(
            M3uExportPlaylist(
                playlist_id=playlist_id,
                title=row["title"],
                filename_m3u=f"{filename_stem}.m3u",
                filename_m3u8=f"{filename_stem}.m3u8",
                rendered=build_m3u_playlist_export(
                    playlist_id,
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


def build_m3u_export_zip(export_package: M3uExportPackage) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for playlist in export_package.playlists:
            content = playlist.rendered.content.encode("utf-8")
            for filename in playlist.filenames(export_package.formats):
                zip_file.writestr(filename, content)

    return archive.getvalue()


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


def _provider_suffix(provider: str) -> str:
    if provider == YOUTUBE_MUSIC_PROVIDER:
        return "yt"

    return re.sub(r"[^A-Za-z0-9]+", "-", provider).strip("-").lower() or "streaming"

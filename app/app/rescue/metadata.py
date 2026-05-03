from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1, ID3, ID3NoHeaderError


class MetadataRescueError(RuntimeError):
    """Raised when local metadata rescue cannot be completed."""


@dataclass(frozen=True, slots=True)
class RescueMetadata:
    title: str
    artist: str
    album: str | None
    year: int | None
    album_art_url: str | None


@dataclass(frozen=True, slots=True)
class ArtworkPayload:
    data: bytes
    mime_type: str
    description: str = "Cover"
    picture_type: int = 3


def write_id3_tags(
    mp3_path: Path | str,
    metadata: RescueMetadata,
    *,
    artwork: ArtworkPayload | None = None,
) -> None:
    path = Path(mp3_path)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    for frame_id in ("TIT2", "TPE1", "TALB", "TDRC", "APIC"):
        tags.delall(frame_id)

    tags.add(TIT2(encoding=3, text=metadata.title))
    tags.add(TPE1(encoding=3, text=metadata.artist))

    if metadata.album:
        tags.add(TALB(encoding=3, text=metadata.album))

    if metadata.year is not None:
        tags.add(TDRC(encoding=3, text=str(metadata.year)))

    if artwork is not None:
        tags.add(
            APIC(
                encoding=3,
                mime=artwork.mime_type,
                type=artwork.picture_type,
                desc=artwork.description,
                data=artwork.data,
            )
        )

    tags.save(path)

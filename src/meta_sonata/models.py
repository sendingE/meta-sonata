from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = {
    ".flac",
    ".mp3",
    ".m4a",
    ".mp4",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".wave",
    ".aiff",
    ".aif",
    ".ape",
}

COVER_FILENAMES = {
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "front.jpg",
    "front.jpeg",
    "front.png",
}


def path_to_json(path: Path) -> str:
    return str(path.expanduser())


@dataclass(frozen=True)
class AlbumMetadata:
    artist: str | None
    album: str | None
    year: str | None = None
    release_date: str | None = None
    label: str | None = None
    catalog_number: str | None = None
    barcode: str | None = None
    release_type: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    artist_aliases: list[str] = field(default_factory=list)
    album_aliases: list[str] = field(default_factory=list)
    edition: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "folder"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "release_date": self.release_date,
            "label": self.label,
            "catalog_number": self.catalog_number,
            "barcode": self.barcode,
            "release_type": self.release_type,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "artist_aliases": self.artist_aliases,
            "album_aliases": self.album_aliases,
            "edition": self.edition,
            "media": self.media,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class AlbumScan:
    path: Path
    audio_files: list[Path]
    cover_file: Path | None = None
    cue_files: list[Path] = field(default_factory=list)
    log_files: list[Path] = field(default_factory=list)
    kind: str = "album"
    group_key: str | None = None
    classification_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": path_to_json(self.path),
            "audio_count": len(self.audio_files),
            "audio_files": [path_to_json(p) for p in self.audio_files],
            "cover_file": path_to_json(self.cover_file) if self.cover_file else None,
            "cue_files": [path_to_json(p) for p in self.cue_files],
            "log_files": [path_to_json(p) for p in self.log_files],
            "kind": self.kind,
            "group_key": self.group_key,
            "classification_reasons": self.classification_reasons,
        }


@dataclass(frozen=True)
class TrackPlan:
    path: Path
    tags: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": path_to_json(self.path),
            "tags": self.tags,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class AlbumPlan:
    path: Path
    metadata: AlbumMetadata
    tracks: list[TrackPlan]
    cover_file: Path | None = None
    remote_cover_url: str | None = None
    protected: bool = False
    warnings: list[str] = field(default_factory=list)
    kind: str = "album"
    group_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": path_to_json(self.path),
            "metadata": self.metadata.to_dict(),
            "track_count": len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
            "cover_file": path_to_json(self.cover_file) if self.cover_file else None,
            "remote_cover_url": self.remote_cover_url,
            "protected": self.protected,
            "warnings": self.warnings,
            "kind": self.kind,
            "group_key": self.group_key,
        }


@dataclass(frozen=True)
class ScrapedTrack:
    title: str | None = None
    artist: str | None = None
    tracknumber: str | None = None
    discnumber: str | None = None
    source_id: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "tracknumber": self.tracknumber,
            "discnumber": self.discnumber,
            "source_id": self.source_id,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class ScrapeCandidate:
    provider: str
    source_id: str
    artist: str | None
    album: str | None
    year: str | None = None
    release_date: str | None = None
    label: str | None = None
    catalog_number: str | None = None
    barcode: str | None = None
    release_type: str | None = None
    cover_url: str | None = None
    source_url: str | None = None
    tracks: list[ScrapedTrack] = field(default_factory=list)
    score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_id": self.source_id,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "release_date": self.release_date,
            "label": self.label,
            "catalog_number": self.catalog_number,
            "barcode": self.barcode,
            "release_type": self.release_type,
            "cover_url": self.cover_url,
            "source_url": self.source_url,
            "track_count": len(self.tracks),
            "tracks": [track.to_dict() for track in self.tracks],
            "score": round(self.score, 3),
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ApplyResult:
    path: Path
    changed: bool
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": path_to_json(self.path),
            "changed": self.changed,
            "skipped": self.skipped,
            "warnings": self.warnings,
        }

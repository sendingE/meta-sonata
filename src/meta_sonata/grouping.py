from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace

from mutagen import File as MutagenFile

from .album_parser import parse_album_dir
from .models import AlbumScan


GENERIC_COLLECTION_RE = re.compile(
    r"(?:车载|網路歌曲|网络歌曲|歌曲合集|音樂合集|音乐合集|playlist|collection|unknown album|未知专辑|未分類|未分类)",
    re.I,
)
DISC_DIR_RE = re.compile(r"^(?:disc|disk|cd)\s*[-_ ]?\s*(\d+)$", re.I)


@dataclass(frozen=True)
class TrackIdentity:
    album: str | None = None
    albumartist: str | None = None
    artist: str | None = None
    tracknumber: str | None = None
    discnumber: str | None = None


def _first(audio, *keys: str) -> str | None:
    for key in keys:
        values = audio.get(key)
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    return None


def read_track_identity(path) -> TrackIdentity:
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None
    if audio is None:
        return TrackIdentity()
    return TrackIdentity(
        album=_first(audio, "album"),
        albumartist=_first(audio, "albumartist", "albumartistsort"),
        artist=_first(audio, "artist"),
        tracknumber=_first(audio, "tracknumber"),
        discnumber=_first(audio, "discnumber"),
    )


def _normalized(value: str | None) -> str:
    return (value or "").strip().casefold()


def _number(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _disc_from_path(path) -> int | None:
    for part in reversed(path.parent.parts):
        match = DISC_DIR_RE.match(part.strip())
        if match:
            return int(match.group(1))
    return None


def _invalid_album_group(entries: list[tuple]) -> str | None:
    positions: set[tuple[int, int]] = set()
    identities = [identity for _, identity in entries]
    for path, identity in entries:
        track = _number(identity.tracknumber)
        if track is None:
            continue
        position = (_number(identity.discnumber) or _disc_from_path(path) or 1, track)
        if position in positions:
            return "duplicate_track_positions"
        positions.add(position)

    album = next((identity.album for identity in identities if identity.album), None)
    albumartists = {_normalized(identity.albumartist) for identity in identities if identity.albumartist}
    artists = {_normalized(identity.artist) for identity in identities if identity.artist}
    if album and GENERIC_COLLECTION_RE.search(album) and not albumartists and len(artists) > 1:
        return "generic_collection_album_tag"
    return None


def group_scan(scan: AlbumScan) -> list[AlbumScan]:
    if not scan.audio_files:
        return [scan]

    identities = {path: read_track_identity(path) for path in scan.audio_files}
    by_album: dict[str, list] = defaultdict(list)
    loose_files = []
    loose_reasons: list[str] = []
    for path, identity in identities.items():
        if identity.album:
            by_album[_normalized(identity.album)].append(path)
        else:
            loose_files.append(path)
            loose_reasons.append("missing_album_tags")

    groups: list[AlbumScan] = []
    for paths in by_album.values():
        album_identities = [identities[path] for path in paths]
        albumartists = {
            _normalized(identity.albumartist): identity.albumartist
            for identity in album_identities
            if identity.albumartist
        }
        artist_buckets: dict[str, list] = defaultdict(list)
        if len(albumartists) > 1:
            for path in paths:
                artist_buckets[_normalized(identities[path].albumartist)].append(path)
        else:
            artist_buckets[""] = paths

        for bucket_paths in artist_buckets.values():
            bucket_identities = [identities[path] for path in bucket_paths]
            invalid_reason = _invalid_album_group(
                [(path, identities[path]) for path in bucket_paths]
            )
            if invalid_reason:
                loose_files.extend(bucket_paths)
                loose_reasons.append(invalid_reason)
                continue
            identity = bucket_identities[0]
            albumartist = next(
                (item.albumartist for item in bucket_identities if item.albumartist),
                None,
            )
            track_artists = {
                item.artist.strip()
                for item in bucket_identities
                if item.artist and item.artist.strip()
            }
            display_artist = albumartist
            if not display_artist and len(track_artists) == 1:
                display_artist = next(iter(track_artists))
            if not display_artist and len(track_artists) > 1:
                display_artist = "Various Artists"
            group_key = f"{display_artist or '?'} - {identity.album}"
            groups.append(
                replace(
                    scan,
                    audio_files=sorted(bucket_paths),
                    kind="album",
                    group_key=group_key,
                    classification_reasons=["consistent_embedded_album_tags"],
                )
            )

    if not by_album and not groups and len(loose_files) == len(scan.audio_files):
        parsed = parse_album_dir(scan.path.name)
        if (
            parsed.artist
            and parsed.album
            and not GENERIC_COLLECTION_RE.search(scan.path.name)
        ):
            return [
                replace(
                    scan,
                    kind="album",
                    group_key=f"{parsed.artist} - {parsed.album}",
                    classification_reasons=["folder_artist_album_identity"],
                )
            ]

    unit_count = len(groups) + int(bool(loose_files))
    if unit_count > 1:
        groups = [replace(group, cover_file=None) for group in groups]
    if loose_files:
        groups.append(
            replace(
                scan,
                audio_files=sorted(set(loose_files)),
                cover_file=None,
                kind="loose",
                group_key=None,
                classification_reasons=sorted(set(loose_reasons))
                or ["missing_or_inconsistent_album_identity"],
            )
        )
    return groups


def group_scans(scans: list[AlbumScan]) -> list[AlbumScan]:
    grouped: list[AlbumScan] = []
    for scan in scans:
        grouped.extend(group_scan(scan))
    return grouped

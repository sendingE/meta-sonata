from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from mutagen import File as MutagenFile

from .models import AlbumMetadata, AlbumPlan, AlbumScan, ScrapeCandidate, ScrapedTrack, TrackPlan
from .safety import is_protected_path
from .tag_hints import local_metadata_for_scan


TRACK_PREFIX_RE = re.compile(r"^\s*(?:CD(?P<disc>\d+)\s*[-_. ]+)?(?P<track>\d{1,3})(?:[.\-_) ]+)(?P<rest>.+)$", re.I)
DISC_FROM_DIR_RE = re.compile(r"(?:disc|disk|cd)\s*[-_ ]?\s*(\d+)", re.I)
VARIOUS_ARTISTS = {"various artists", "va", "群星", "合辑", "合輯"}


def _existing_track_tags(path: Path) -> dict[str, str]:
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None
    if audio is None:
        return {}

    tags: dict[str, str] = {}
    for key in (
        "title",
        "artist",
        "album",
        "albumartist",
        "date",
        "tracknumber",
        "discnumber",
        "genre",
        "label",
        "catalognumber",
        "barcode",
        "musicbrainz_albumid",
        "musicbrainz_trackid",
        "musicinfo_source",
    ):
        values = audio.get(key)
        if values and str(values[0]).strip():
            tags[key] = str(values[0]).strip()
    if "label" not in tags:
        values = audio.get("publisher")
        if values and str(values[0]).strip():
            tags["label"] = str(values[0]).strip()
    return tags


def _strip_extension(path: Path) -> str:
    return path.name[: -len(path.suffix)] if path.suffix else path.name


def _infer_disc(path: Path) -> str | None:
    for part in reversed(path.parent.parts):
        m = DISC_FROM_DIR_RE.search(part)
        if m:
            return str(int(m.group(1)))
    m = TRACK_PREFIX_RE.match(_strip_extension(path))
    if m and m.group("disc"):
        return str(int(m.group("disc")))
    return None


def _infer_track(path: Path) -> str | None:
    m = TRACK_PREFIX_RE.match(_strip_extension(path))
    if m:
        return str(int(m.group("track")))
    return None


def _number(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    return str(int(m.group(0)))


def _infer_title_and_artist(path: Path, fallback_artist: str | None) -> tuple[str | None, str | None]:
    stem = _strip_extension(path)
    m = TRACK_PREFIX_RE.match(stem)
    if not m:
        return None, None
    rest = m.group("rest").strip()
    parts = re.split(r"\s+(?:-|–|—)\s+", rest, maxsplit=1)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        if fallback_artist and left.casefold() == fallback_artist.casefold():
            return right, fallback_artist
        return right, left
    return rest, None


def _infer_loose_title_and_artist(path: Path) -> tuple[str, str | None]:
    stem = _strip_extension(path).strip()
    match = TRACK_PREFIX_RE.match(stem)
    value = match.group("rest").strip() if match else stem
    parts = re.split(r"\s+(?:-|–|—)\s+", value, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip()
    return value, None


def _is_compilation(artist: str | None) -> bool:
    return (artist or "").strip().casefold() in VARIOUS_ARTISTS


def merge_metadata(local: AlbumMetadata, scraped: ScrapeCandidate | None) -> AlbumMetadata:
    if scraped is None:
        return local
    return replace(
        local,
        artist=local.artist or scraped.artist,
        album=local.album or scraped.album,
        year=local.year or scraped.year,
        release_date=scraped.release_date,
        label=scraped.label,
        catalog_number=scraped.catalog_number,
        barcode=scraped.barcode,
        release_type=scraped.release_type,
        source=f"{local.source}+{scraped.provider}",
        source_id=scraped.source_id,
        source_url=scraped.source_url,
        confidence=max(local.confidence, scraped.score),
        warnings=local.warnings + scraped.warnings,
    )


def _scraped_track_map(scraped: ScrapeCandidate | None) -> dict[tuple[str | None, str | None], ScrapedTrack]:
    if scraped is None:
        return {}
    mapped: dict[tuple[str | None, str | None], ScrapedTrack] = {}
    for track in scraped.tracks:
        key = (_number(track.discnumber), _number(track.tracknumber))
        if key[1] and key not in mapped:
            mapped[key] = track
        fallback = (None, key[1])
        if key[1] and fallback not in mapped:
            mapped[fallback] = track
    return mapped


def build_album_plan(
    scan: AlbumScan,
    *,
    scraped: ScrapeCandidate | None = None,
    min_scrape_score: float = 0.72,
) -> AlbumPlan:
    local_metadata = local_metadata_for_scan(scan)
    accepted_scrape = scraped if scraped and scraped.score >= min_scrape_score else None
    metadata = merge_metadata(local_metadata, accepted_scrape)
    warnings = list(metadata.warnings)
    if scraped and accepted_scrape is None:
        warnings.append(f"scrape_candidate_below_threshold:{scraped.provider}:{scraped.score:.2f}")
    if not scan.audio_files:
        warnings.append("no_audio_files")
    if not scan.cover_file:
        warnings.append("no_local_cover_file")

    tracks: list[TrackPlan] = []
    scraped_tracks = _scraped_track_map(accepted_scrape)
    for audio in scan.audio_files:
        tags: dict[str, str] = {}
        track_warnings: list[str] = []
        existing = _existing_track_tags(audio)

        if existing.get("album") or metadata.album:
            tags["album"] = existing.get("album") or metadata.album
        if existing.get("albumartist") or metadata.artist:
            tags["albumartist"] = existing.get("albumartist") or metadata.artist
        if existing.get("artist"):
            tags["artist"] = existing["artist"]
        elif metadata.artist and not _is_compilation(metadata.artist):
            tags["artist"] = metadata.artist
        if existing.get("date") or metadata.year:
            tags["date"] = existing.get("date") or metadata.year
        elif metadata.release_date:
            tags["date"] = metadata.release_date
        if existing.get("genre"):
            tags["genre"] = existing["genre"]
        if existing.get("label") or metadata.label:
            tags["label"] = existing.get("label") or metadata.label
        if existing.get("catalognumber") or metadata.catalog_number:
            tags["catalognumber"] = existing.get("catalognumber") or metadata.catalog_number
        if existing.get("barcode") or metadata.barcode:
            tags["barcode"] = existing.get("barcode") or metadata.barcode
        if metadata.source_id:
            if accepted_scrape and accepted_scrape.provider == "musicbrainz":
                tags["musicbrainz_albumid"] = existing.get("musicbrainz_albumid") or metadata.source_id
            tags["musicinfo_source"] = existing.get("musicinfo_source") or (
                f"{accepted_scrape.provider}:{metadata.source_id}" if accepted_scrape else metadata.source_id
            )

        track = existing.get("tracknumber") or _infer_track(audio)
        if track:
            tags["tracknumber"] = track
        else:
            track_warnings.append("track_number_not_inferred")

        disc = existing.get("discnumber") or _infer_disc(audio)
        if disc:
            tags["discnumber"] = disc

        scraped_track = scraped_tracks.get((_number(disc), _number(track))) or scraped_tracks.get((None, _number(track)))
        if not disc and scraped_track and scraped_track.discnumber:
            tags["discnumber"] = scraped_track.discnumber
        title, per_track_artist = _infer_title_and_artist(audio, metadata.artist)
        if existing.get("title"):
            tags["title"] = existing["title"]
        elif title:
            tags["title"] = title
        elif scraped_track and scraped_track.title:
            tags["title"] = scraped_track.title
        if per_track_artist and _is_compilation(metadata.artist):
            tags["artist"] = per_track_artist
        elif "artist" not in tags and scraped_track and scraped_track.artist:
            tags["artist"] = scraped_track.artist
        if scraped_track and scraped_track.source_id:
            if accepted_scrape and accepted_scrape.provider == "musicbrainz":
                tags["musicbrainz_trackid"] = existing.get("musicbrainz_trackid") or scraped_track.source_id

        if not tags:
            track_warnings.append("no_tags_planned")

        tracks.append(TrackPlan(path=audio, tags=tags, warnings=track_warnings))

    return AlbumPlan(
        path=scan.path,
        metadata=metadata,
        tracks=tracks,
        cover_file=scan.cover_file,
        remote_cover_url=None if scan.cover_file else (accepted_scrape.cover_url if accepted_scrape else None),
        protected=is_protected_path(scan.path),
        warnings=warnings,
        kind=scan.kind,
        group_key=scan.group_key,
    )


def build_loose_plan(scan: AlbumScan) -> AlbumPlan:
    tracks: list[TrackPlan] = []
    for audio in scan.audio_files:
        existing = _existing_track_tags(audio)
        tags = {
            key: value
            for key, value in existing.items()
            if key
            in {
                "title",
                "artist",
                "date",
                "tracknumber",
                "discnumber",
                "genre",
                "musicbrainz_trackid",
                "musicinfo_source",
            }
        }
        inferred_title, inferred_artist = _infer_loose_title_and_artist(audio)
        if not tags.get("title"):
            tags["title"] = inferred_title or _strip_extension(audio)
        if not tags.get("artist") and inferred_artist:
            tags["artist"] = inferred_artist
        track_warnings = []
        if not tags.get("artist"):
            track_warnings.append("loose_track_artist_not_inferred")
        tracks.append(TrackPlan(path=audio, tags=tags, warnings=track_warnings))

    reasons = scan.classification_reasons or ["loose_tracks"]
    return AlbumPlan(
        path=scan.path,
        metadata=AlbumMetadata(
            artist=None,
            album=None,
            confidence=0.0,
            source="per-track",
            warnings=reasons,
        ),
        tracks=tracks,
        cover_file=None,
        remote_cover_url=None,
        protected=is_protected_path(scan.path),
        warnings=reasons,
        kind="loose",
        group_key=None,
    )


def build_plans(scans: list[AlbumScan]) -> list[AlbumPlan]:
    return [build_loose_plan(scan) if scan.kind == "loose" else build_album_plan(scan) for scan in scans]

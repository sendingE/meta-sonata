from __future__ import annotations

from collections import Counter

from mutagen import File as MutagenFile

from .album_parser import parse_album_dir
from .models import AlbumMetadata, AlbumScan


def _first_tag(audio, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        values = audio.get(key)
        if values:
            value = str(values[0]).strip()
            if value:
                return value
    return None


def _common(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    value, count = counter.most_common(1)[0]
    if count <= 0:
        return None
    return value


def infer_metadata_from_existing_tags(scan: AlbumScan) -> AlbumMetadata:
    artists: Counter[str] = Counter()
    albumartists: Counter[str] = Counter()
    albums: Counter[str] = Counter()
    years: Counter[str] = Counter()

    for path in scan.audio_files:
        try:
            audio = MutagenFile(str(path), easy=True)
        except Exception:
            audio = None
        if audio is None:
            continue

        artist = _first_tag(audio, ("artist",))
        albumartist = _first_tag(audio, ("albumartist", "albumartistsort"))
        album = _first_tag(audio, ("album",))
        date = _first_tag(audio, ("date", "year", "originaldate"))

        if artist:
            artists[artist] += 1
        if albumartist:
            albumartists[albumartist] += 1
        if album:
            albums[album] += 1
        if date:
            years[date[:4]] += 1

    artist = _common(albumartists) or _common(artists)
    album = _common(albums)
    year = _common(years)
    confidence = 0.0
    warnings: list[str] = []
    if artist or album or year:
        confidence = 0.7
        warnings.append("metadata_from_existing_tags")

    return AlbumMetadata(
        artist=artist,
        album=album,
        year=year,
        confidence=confidence,
        source="existing-tags",
        warnings=warnings,
    )


def local_metadata_for_scan(scan: AlbumScan) -> AlbumMetadata:
    parsed = parse_album_dir(scan.path.name)
    hints = infer_metadata_from_existing_tags(scan)
    warnings = list(parsed.warnings)
    if hints.warnings:
        warnings.extend(hints.warnings)

    for field in ("artist", "album", "year"):
        parsed_value = getattr(parsed, field)
        hint_value = getattr(hints, field)
        if parsed_value and hint_value and parsed_value.strip().casefold() != hint_value.strip().casefold():
            warnings.append(f"folder_{field}_conflicts_with_existing_tags")

    confidence = parsed.confidence
    if hints.confidence:
        confidence = max(confidence, hints.confidence)
    if hints.artist and not parsed.artist:
        confidence = max(confidence, 0.78)
    if hints.album and not parsed.album:
        confidence = max(confidence, 0.78)

    folder_matches_embedded_identity = True
    if hints.album:
        folder_matches_embedded_identity = bool(
            parsed.album
            and parsed.album.strip().casefold() == hints.album.strip().casefold()
        )
    if folder_matches_embedded_identity and hints.artist and parsed.artist:
        folder_matches_embedded_identity = (
            parsed.artist.strip().casefold() == hints.artist.strip().casefold()
        )
    year = hints.year or (parsed.year if folder_matches_embedded_identity else None)

    return AlbumMetadata(
        artist=hints.artist or parsed.artist,
        album=hints.album or parsed.album,
        year=year,
        artist_aliases=parsed.artist_aliases,
        album_aliases=parsed.album_aliases,
        edition=parsed.edition,
        media=parsed.media,
        confidence=confidence,
        source="existing-tags+folder" if hints.confidence else parsed.source,
        warnings=warnings,
    )

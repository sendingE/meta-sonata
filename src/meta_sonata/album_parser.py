from __future__ import annotations

import re
from pathlib import Path

from .models import AlbumMetadata


YEAR_RE = re.compile(r"(?:^|[^\d])((?:1[5-9]|20)\d{2})(?:[^\d]|$)")
YEAR_PREFIX_RE = re.compile(r"^\s*((?:1[5-9]|20)\d{2})\s+(?:-|–|—)\s+(.+)$")
BRACKET_RE = re.compile(r"(\[[^\]]+\]|\{[^}]+\}|\([^)]*\))")
INLINE_ALIAS_PAIR_RE = re.compile(
    r"^\s*.+?\s*\((?P<artist_alias>[^()]*)\)\s+(?:-|–|—)\s+.+?\s*\((?P<album_alias>[^()]*)\)"
)
LEADING_INDEX_RE = re.compile(r"^\s*\d{1,3}\s+")
SEPARATOR_RE = re.compile(r"\s+(?:-|–|—)\s+")
MEDIA_TOKENS = {
    "FLAC",
    "WAV",
    "WEB",
    "CD",
    "SACD",
    "MP3",
    "AAC",
    "HI-RES",
    "HIRES",
    "24-96",
    "24BIT",
}


def _clean_token(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "([{" and value[-1] in ")]}":
        value = value[1:-1]
    return " ".join(value.split()).strip()


def _split_brackets(name: str) -> tuple[str, list[str], list[str], str | None]:
    edition: list[str] = []
    media: list[str] = []
    year: str | None = None

    def replace(match: re.Match[str]) -> str:
        nonlocal year
        token = _clean_token(match.group(0))
        ym = YEAR_RE.search(token)
        if ym and year is None:
            year = ym.group(1)
        upper = token.upper()
        if any(part in upper for part in MEDIA_TOKENS):
            media.append(token)
        elif token and not ym:
            edition.append(token)
        return " "

    base = BRACKET_RE.sub(replace, name)
    return " ".join(base.split()), edition, media, year


def parse_album_dir(path_or_name: Path | str) -> AlbumMetadata:
    raw_name = Path(path_or_name).name if isinstance(path_or_name, Path) else str(path_or_name)
    alias_match = INLINE_ALIAS_PAIR_RE.match(raw_name)
    artist_aliases: list[str] = []
    album_aliases: list[str] = []
    if alias_match:
        artist_alias = _clean_token(alias_match.group("artist_alias"))
        album_alias = _clean_token(alias_match.group("album_alias"))
        if artist_alias and not YEAR_RE.fullmatch(artist_alias):
            artist_aliases.append(artist_alias)
        if album_alias and not YEAR_RE.fullmatch(album_alias):
            album_aliases.append(album_alias)
    name = LEADING_INDEX_RE.sub("", raw_name).strip()
    base, edition, media, bracket_year = _split_brackets(name)

    year = bracket_year
    prefix_album: str | None = None
    prefix = YEAR_PREFIX_RE.match(base)
    if prefix:
        year = year or prefix.group(1)
        prefix_album = prefix.group(2).strip()
        base = prefix_album

    ym = YEAR_RE.search(base)
    if ym and year is None:
        year = ym.group(1)
        base = (base[: ym.start(1)] + base[ym.end(1) :]).strip()
        base = " ".join(base.replace("()", " ").split())

    artist: str | None = None
    album: str | None = None
    confidence = 0.35
    warnings: list[str] = []

    parts = SEPARATOR_RE.split(base, maxsplit=1)
    if prefix_album:
        album = prefix_album.strip(" .-_")
        confidence = 0.58
        warnings.append("folder_name_has_year_album_without_artist")
    elif len(parts) == 2:
        left = parts[0].strip(" .-_")
        right = parts[1].strip(" .-_")
        if YEAR_RE.fullmatch(left):
            year = year or left
            album = right
            confidence = 0.58
            warnings.append("folder_name_has_year_album_without_artist")
        else:
            artist = left
            album = right
            confidence = 0.82
    else:
        # Common OpenCD-ish form: Album-Artist, but keep this lower confidence.
        compact_parts = re.split(r"(?<!\d)-(?!\d)", base, maxsplit=1)
        if len(compact_parts) == 2 and all(p.strip() for p in compact_parts):
            left, right = [p.strip(" .-_") for p in compact_parts]
            if len(left) > len(right):
                album, artist = left, right
            else:
                artist, album = left, right
            confidence = 0.55
            warnings.append("ambiguous_dash_separator")

    if not artist or not album:
        warnings.append("folder_name_not_parsed_as_artist_album")

    if year:
        confidence += 0.05
    if edition or media:
        confidence += 0.03

    return AlbumMetadata(
        artist=artist or None,
        album=album or None,
        year=year,
        artist_aliases=artist_aliases,
        album_aliases=album_aliases,
        edition=edition,
        media=media,
        confidence=min(confidence, 0.95),
        warnings=warnings,
    )

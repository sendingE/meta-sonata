from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from mutagen import File as MutagenFile

from .matching import normalize_text, text_similarity
from .network import fetch_json


TRACK_PREFIX_RE = re.compile(r"^\s*\d{1,3}(?:[.\-_) ]+)\s*(.+)$")
ARTIST_TITLE_RE = re.compile(r"^\s*(.+?)\s+(?:-|–|—)\s+(.+?)\s*$")
DEFAULT_TRACK_SOURCES = ("itunes", "netease", "musicbrainz")
MIN_TRACK_SCORE = 0.78
PROMOTIONAL_GENRE_RE = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|cn|net|org|cc)(?![a-z])|分享|下载|下載|论坛|論壇|音乐网|音樂網)",
    re.I,
)


@dataclass(frozen=True)
class LocalTrackIdentity:
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class TrackCandidate:
    provider: str
    source_id: str
    title: str
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    release_date: str | None = None
    genre: str | None = None
    track_number: str | None = None
    disc_number: str | None = None
    cover_url: str | None = None
    source_url: str | None = None
    duration_ms: int | None = None
    score: float = 0.0
    artist_ids: tuple[str, ...] = ()
    recording_id: str | None = None
    release_id: str | None = None
    release_group_id: str | None = None
    release_track_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_id": self.source_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "release_date": self.release_date,
            "genre": self.genre,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "cover_url": self.cover_url,
            "source_url": self.source_url,
            "duration_ms": self.duration_ms,
            "score": round(self.score, 3),
            "artist_ids": list(self.artist_ids),
            "recording_id": self.recording_id,
            "release_id": self.release_id,
            "release_group_id": self.release_group_id,
            "release_track_id": self.release_track_id,
        }


@dataclass(frozen=True)
class TrackResolution:
    local: LocalTrackIdentity
    candidate: TrackCandidate | None
    candidates: list[TrackCandidate]
    warnings: list[str]


TrackSearcher = Callable[[LocalTrackIdentity, int], list[TrackCandidate]]


def _first(audio, key: str) -> str | None:
    try:
        values = audio.get(key)
    except Exception:
        values = None
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None


def _filename_identity(path: Path) -> tuple[str, str | None]:
    value = path.stem.strip()
    prefix = TRACK_PREFIX_RE.match(value)
    if prefix:
        value = prefix.group(1).strip()
    match = ARTIST_TITLE_RE.match(value)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    return value, None


def local_track_identity(path: Path) -> LocalTrackIdentity:
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None
    inferred_title, inferred_artist = _filename_identity(path)
    info = getattr(audio, "info", None)
    length = getattr(info, "length", None)
    try:
        duration_ms = round(float(length) * 1000) if length is not None else None
    except (TypeError, ValueError):
        duration_ms = None
    return LocalTrackIdentity(
        title=_first(audio, "title") or inferred_title,
        artist=_first(audio, "artist") or inferred_artist,
        album=_first(audio, "album"),
        duration_ms=duration_ms,
    )


def _query(identity: LocalTrackIdentity) -> str:
    return " ".join(part for part in (identity.artist, identity.title) if part)


def search_itunes_tracks(identity: LocalTrackIdentity, limit: int = 5) -> list[TrackCandidate]:
    query = _query(identity)
    if not query:
        return []
    candidates: list[TrackCandidate] = []
    seen: set[str] = set()
    for country in ("TW", "HK", "CN", "US", "JP"):
        params = urllib.parse.urlencode(
            {
                "term": query,
                "entity": "song",
                "media": "music",
                "limit": max(limit, 5),
                "country": country,
            }
        )
        data = fetch_json(f"https://itunes.apple.com/search?{params}")
        for item in data.get("results", []):
            source_id = str(item.get("trackId") or "")
            if not source_id or source_id in seen or not item.get("trackName"):
                continue
            seen.add(source_id)
            cover = item.get("artworkUrl100")
            if cover:
                cover = cover.replace("100x100bb", "1200x1200bb")
            release_date = (item.get("releaseDate") or "")[:10] or None
            candidates.append(
                TrackCandidate(
                    provider="itunes",
                    source_id=source_id,
                    title=item["trackName"],
                    artist=item.get("artistName"),
                    album=item.get("collectionName"),
                    album_artist=item.get("artistName"),
                    release_date=release_date,
                    genre=item.get("primaryGenreName"),
                    track_number=str(item.get("trackNumber") or "") or None,
                    disc_number=str(item.get("discNumber") or "") or None,
                    cover_url=cover,
                    source_url=item.get("trackViewUrl"),
                    duration_ms=item.get("trackTimeMillis"),
                )
            )
        if len(candidates) >= limit:
            break
    return candidates[: max(limit, 1) * 2]


def search_netease_tracks(identity: LocalTrackIdentity, limit: int = 5) -> list[TrackCandidate]:
    query = _query(identity)
    if not query:
        return []
    params = urllib.parse.urlencode(
        {"type": "1", "s": query, "limit": str(limit), "offset": "0"}
    )
    headers = {"Referer": "https://music.163.com/", "Host": "music.163.com"}
    data = fetch_json(
        f"https://music.163.com/api/cloudsearch/pc?{params}", headers=headers
    )
    candidates: list[TrackCandidate] = []
    for item in data.get("result", {}).get("songs", []) or []:
        source_id = str(item.get("id") or "")
        if not source_id or not item.get("name"):
            continue
        artists = item.get("ar") or item.get("artists") or []
        artist = artists[0].get("name") if artists else None
        album = item.get("al") or item.get("album") or {}
        candidates.append(
            TrackCandidate(
                provider="netease",
                source_id=source_id,
                title=item["name"],
                artist=artist,
                album=album.get("name"),
                album_artist=artist,
                cover_url=album.get("picUrl"),
                source_url=f"https://music.163.com/#/song?id={source_id}",
                duration_ms=item.get("dt") or item.get("duration"),
                track_number=str(item.get("no") or "") or None,
                disc_number=str(item.get("cd") or "") or None,
            )
        )
    return candidates


def _artist_credit(row: dict[str, Any]) -> str | None:
    values = row.get("artist-credit") or []
    if values and isinstance(values[0], dict):
        return values[0].get("name") or (values[0].get("artist") or {}).get("name")
    return None


def _artist_ids(row: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for credit in row.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist_id = str((credit.get("artist") or {}).get("id") or "").strip()
        if artist_id and artist_id not in values:
            values.append(artist_id)
    return tuple(values)


def search_musicbrainz_tracks(identity: LocalTrackIdentity, limit: int = 5) -> list[TrackCandidate]:
    if not identity.title:
        return []
    terms = [f'recording:"{identity.title}"']
    if identity.artist:
        terms.append(f'artist:"{identity.artist}"')
    params = urllib.parse.urlencode(
        {"query": " AND ".join(terms), "fmt": "json", "limit": limit}
    )
    data = fetch_json(f"https://musicbrainz.org/ws/2/recording/?{params}")
    candidates: list[TrackCandidate] = []
    for item in data.get("recordings", []) or []:
        source_id = str(item.get("id") or "")
        if not source_id or not item.get("title"):
            continue
        release = (item.get("releases") or [{}])[0]
        release_id = str(release.get("id") or "")
        release_group_id = str((release.get("release-group") or {}).get("id") or "")
        date = release.get("date") or release.get("first-release-date")
        candidates.append(
            TrackCandidate(
                provider="musicbrainz",
                source_id=source_id,
                title=item["title"],
                artist=_artist_credit(item),
                album=release.get("title"),
                album_artist=_artist_credit(release) or _artist_credit(item),
                release_date=date,
                cover_url=(
                    f"https://coverartarchive.org/release/{release_id}/front-500"
                    if release_id
                    else None
                ),
                source_url=f"https://musicbrainz.org/recording/{source_id}",
                duration_ms=item.get("length"),
                artist_ids=_artist_ids(item),
                recording_id=source_id,
                release_id=release_id or None,
                release_group_id=release_group_id or None,
            )
        )
    return candidates


def score_track_candidate(identity: LocalTrackIdentity, candidate: TrackCandidate) -> float:
    title_score = text_similarity(identity.title, candidate.title)
    artist_score = text_similarity(identity.artist, candidate.artist)
    album_score = text_similarity(identity.album, candidate.album)
    if identity.artist:
        score = 0.64 * title_score + 0.26 * artist_score
    else:
        score = 0.82 * title_score
    if identity.album:
        score += 0.08 * album_score
    duration_bonus = 0.0
    if identity.duration_ms and candidate.duration_ms:
        delta = abs(identity.duration_ms - candidate.duration_ms)
        if delta <= 1_500:
            duration_bonus = 0.10
        elif delta <= 4_000:
            duration_bonus = 0.05
        elif delta > 10_000:
            duration_bonus = -0.20
    score += duration_bonus
    if title_score < 0.62:
        score -= 0.25
    if identity.artist and candidate.artist and artist_score < 0.45:
        score -= 0.15
    return max(0.0, min(1.0, score))


def is_promotional_genre(value: str | None) -> bool:
    return bool(value and PROMOTIONAL_GENRE_RE.search(value))


def resolve_track(
    path: Path,
    *,
    source_names: tuple[str, ...] = DEFAULT_TRACK_SOURCES,
    limit_per_source: int = 5,
    min_score: float = MIN_TRACK_SCORE,
    searchers: dict[str, TrackSearcher] | None = None,
) -> TrackResolution:
    identity = local_track_identity(path)
    available = searchers or {
        "itunes": search_itunes_tracks,
        "netease": search_netease_tracks,
        "musicbrainz": search_musicbrainz_tracks,
    }
    candidates: list[TrackCandidate] = []
    warnings: list[str] = []
    for source in source_names:
        searcher = available.get(source)
        if not searcher:
            continue
        try:
            candidates.extend(searcher(identity, limit_per_source))
        except Exception as exc:
            warnings.append(f"{source}_error:{exc}")
    scored = [replace(row, score=score_track_candidate(identity, row)) for row in candidates]
    scored.sort(key=lambda row: row.score, reverse=True)
    accepted = scored[0] if scored and scored[0].score >= min_score else None
    if scored and accepted is None:
        warnings.append(f"best_candidate_below_threshold:{scored[0].score:.2f}")
    if accepted and len(scored) > 1:
        runner_up = scored[1]
        conflicts = (
            text_similarity(accepted.title, runner_up.title) < 0.95
            or text_similarity(accepted.artist, runner_up.artist) < 0.90
        )
        if conflicts and accepted.score - runner_up.score < 0.025:
            warnings.append("ambiguous_track_identity")
            accepted = None
    if accepted:
        release_peers = [
            row
            for row in scored
            if accepted.score - row.score < 0.03
            and text_similarity(accepted.title, row.title) >= 0.95
            and text_similarity(accepted.artist, row.artist) >= 0.90
            and row.album
        ]
        release_names = {normalize_text(row.album) for row in release_peers if row.album}
        if len(release_names) > 1 and not identity.album:
            warnings.append("ambiguous_release_identity")
            accepted = replace(
                accepted,
                album=None,
                release_date=None,
                track_number=None,
                disc_number=None,
                cover_url=None,
                release_id=None,
                release_group_id=None,
                release_track_id=None,
            )
    return TrackResolution(
        local=identity,
        candidate=accepted,
        candidates=scored,
        warnings=warnings,
    )


def completed_track_tags(path: Path, resolution: TrackResolution) -> dict[str, str]:
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None
    tags: dict[str, str] = {}
    for key in (
        "title",
        "artist",
        "album",
        "albumartist",
        "date",
        "genre",
        "tracknumber",
        "discnumber",
    ):
        value = _first(audio, key)
        if value:
            tags[key] = value

    candidate = resolution.candidate
    if candidate is None:
        tags.setdefault("title", resolution.local.title)
        if resolution.local.artist:
            tags.setdefault("artist", resolution.local.artist)
        return tags

    values = {
        "title": candidate.title,
        "artist": candidate.artist,
        "album": candidate.album,
        "albumartist": candidate.album_artist or candidate.artist,
        "date": candidate.release_date,
        "genre": candidate.genre,
        "tracknumber": candidate.track_number,
        "discnumber": candidate.disc_number,
    }
    for key, value in values.items():
        if value:
            if key == "genre" and is_promotional_genre(tags.get(key)):
                tags[key] = value
            else:
                tags.setdefault(key, value)
    tags["musicinfo_source"] = f"{candidate.provider}:{candidate.source_id}"
    if candidate.provider == "musicbrainz":
        tags["musicbrainz_recordingid"] = candidate.recording_id or candidate.source_id
        if candidate.release_id:
            tags["musicbrainz_albumid"] = candidate.release_id
        if candidate.release_group_id:
            tags["musicbrainz_releasegroupid"] = candidate.release_group_id
        if candidate.release_track_id:
            tags["musicbrainz_trackid"] = candidate.release_track_id
        if candidate.artist_ids:
            tags["musicbrainz_artistid"] = "; ".join(candidate.artist_ids)
    return tags

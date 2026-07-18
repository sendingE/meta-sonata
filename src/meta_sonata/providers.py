from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import replace
from typing import Any

from .matching import duration_mismatch_ms, score_candidate
from .models import AlbumMetadata, ScrapeCandidate, ScrapedTrack


USER_AGENT = "meta-sonata/0.1 (+local metadata workflow)"
DEFAULT_TIMEOUT = 15
ALIAS_QUERY_THRESHOLD = 0.72


class ProviderError(RuntimeError):
    pass


def fetch_json(url: str, *, timeout: int = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None) -> Any:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return json.loads(res.read().decode(charset, errors="replace"))


def build_query(local: AlbumMetadata) -> str:
    parts = [part for part in (local.artist, local.album, local.year) if part]
    return " ".join(parts)


def _first_artist(value: Any) -> str | None:
    if isinstance(value, list) and value:
        item = value[0]
        if isinstance(item, dict):
            return item.get("name") or item.get("artist", {}).get("name")
    return None


class AlbumProvider:
    name = "base"
    display_name = "Base"
    implemented = False
    note = ""

    def search(self, local: AlbumMetadata, *, limit: int = 5) -> list[ScrapeCandidate]:
        raise NotImplementedError


class MusicBrainzProvider(AlbumProvider):
    name = "musicbrainz"
    display_name = "MusicBrainz"
    implemented = True
    note = "official public metadata; pairs well with Cover Art Archive"

    def search(self, local: AlbumMetadata, *, limit: int = 5) -> list[ScrapeCandidate]:
        if not local.album:
            return []
        terms = [f'release:"{local.album}"']
        if local.artist:
            terms.append(f'artist:"{local.artist}"')
        if local.year:
            terms.append(f'date:{local.year}')
        params = urllib.parse.urlencode({"query": " AND ".join(terms), "fmt": "json", "limit": limit})
        url = f"https://musicbrainz.org/ws/2/release/?{params}"
        data = fetch_json(url)
        candidates: list[ScrapeCandidate] = []
        for release in data.get("releases", [])[:limit]:
            release_id = release.get("id")
            if not release_id:
                continue
            detail = self._detail(release_id)
            candidate = self._candidate_from_release(detail or release)
            if candidate:
                candidates.append(candidate)
            time.sleep(0.15)
        return candidates

    def _detail(self, release_id: str) -> dict[str, Any] | None:
        inc = "recordings+artist-credits+labels+release-groups+media"
        params = urllib.parse.urlencode({"fmt": "json", "inc": inc})
        try:
            return fetch_json(f"https://musicbrainz.org/ws/2/release/{release_id}?{params}")
        except Exception:
            return None

    def _candidate_from_release(self, release: dict[str, Any]) -> ScrapeCandidate | None:
        release_id = release.get("id")
        if not release_id:
            return None
        date = release.get("date") or ""
        artist = _first_artist(release.get("artist-credit")) or release.get("artist-credit-phrase")
        label_info = (release.get("label-info") or [{}])[0] if release.get("label-info") else {}
        label = (label_info.get("label") or {}).get("name")
        catalog = label_info.get("catalog-number")
        release_group = release.get("release-group") or {}
        release_type = ", ".join(
            str(x)
            for x in ([release_group.get("primary-type")] + release_group.get("secondary-types", []))
            if x
        )
        tracks: list[ScrapedTrack] = []
        for medium in release.get("media", []) or []:
            disc = str(medium.get("position") or "") or None
            for item in medium.get("tracks", []) or []:
                rec = item.get("recording") or {}
                tracks.append(
                    ScrapedTrack(
                        title=item.get("title") or rec.get("title"),
                        artist=_first_artist(item.get("artist-credit")) or artist,
                        tracknumber=str(item.get("number") or item.get("position") or "") or None,
                        discnumber=disc,
                        source_id=rec.get("id") or item.get("id"),
                        duration_ms=item.get("length") or rec.get("length"),
                    )
                )
        cover_archive = release.get("cover-art-archive") or {}
        release_group_id = release_group.get("id")
        cover_url = None
        if cover_archive.get("front"):
            cover_url = f"https://coverartarchive.org/release/{release_id}/front-500"
        elif release_group_id:
            cover_url = f"https://coverartarchive.org/release-group/{release_group_id}/front-500"
        return ScrapeCandidate(
            provider=self.name,
            source_id=release_id,
            artist=artist,
            album=release.get("title"),
            year=date[:4] if date else None,
            release_date=date or None,
            label=label,
            catalog_number=catalog,
            barcode=release.get("barcode"),
            release_type=release_type or None,
            cover_url=cover_url,
            source_url=f"https://musicbrainz.org/release/{release_id}",
            tracks=tracks,
        )


class ITunesProvider(AlbumProvider):
    name = "itunes"
    display_name = "Apple/iTunes"
    implemented = True
    note = "public iTunes Search API; good for covers and commercial release data"

    countries = ("TW", "HK", "CN", "US", "JP")

    def search(self, local: AlbumMetadata, *, limit: int = 5) -> list[ScrapeCandidate]:
        query = build_query(local)
        if not query:
            return []
        candidates: list[ScrapeCandidate] = []
        seen: set[str] = set()
        per_country_limit = max(2, limit)
        for country in self.countries:
            params = urllib.parse.urlencode(
                {
                    "term": query,
                    "entity": "album",
                    "media": "music",
                    "limit": per_country_limit,
                    "country": country,
                }
            )
            data = fetch_json(f"https://itunes.apple.com/search?{params}")
            for item in data.get("results", []):
                cid = str(item.get("collectionId") or "")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                detail = self._lookup(cid, country)
                candidate = self._candidate_from_collection(item, detail, country)
                if candidate:
                    candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates[:limit]

    def _lookup(self, collection_id: str, country: str) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {"id": collection_id, "entity": "song", "limit": 200, "country": country}
        )
        try:
            return fetch_json(f"https://itunes.apple.com/lookup?{params}")
        except Exception:
            return {"results": []}

    def _candidate_from_collection(
        self,
        item: dict[str, Any],
        detail: dict[str, Any],
        country: str,
    ) -> ScrapeCandidate | None:
        cid = str(item.get("collectionId") or "")
        if not cid:
            return None
        release_date = (item.get("releaseDate") or "")[:10] or None
        cover = item.get("artworkUrl100")
        if cover:
            cover = cover.replace("100x100bb", "1200x1200bb")
        tracks: list[ScrapedTrack] = []
        for row in detail.get("results", []):
            if row.get("wrapperType") != "track":
                continue
            tracks.append(
                ScrapedTrack(
                    title=row.get("trackName"),
                    artist=row.get("artistName"),
                    tracknumber=str(row.get("trackNumber") or "") or None,
                    discnumber=str(row.get("discNumber") or "") or None,
                    source_id=str(row.get("trackId") or "") or None,
                    duration_ms=row.get("trackTimeMillis"),
                )
            )
        return ScrapeCandidate(
            provider=self.name,
            source_id=cid,
            artist=item.get("artistName"),
            album=item.get("collectionName"),
            year=release_date[:4] if release_date else None,
            release_date=release_date,
            release_type=item.get("collectionType"),
            cover_url=cover,
            source_url=item.get("collectionViewUrl"),
            tracks=tracks,
            warnings=[f"country={country}"],
        )


class NeteaseProvider(AlbumProvider):
    name = "netease"
    display_name = "NetEase Cloud Music"
    implemented = True
    note = "unofficial public web endpoints; useful Chinese metadata, may be flaky"

    headers = {
        "Referer": "https://music.163.com/",
        "Host": "music.163.com",
    }

    def search(self, local: AlbumMetadata, *, limit: int = 5) -> list[ScrapeCandidate]:
        query = build_query(local)
        if not query:
            return []
        params = urllib.parse.urlencode({"type": "10", "s": query, "limit": limit, "offset": "0"})
        data = fetch_json(f"https://music.163.com/api/cloudsearch/pc?{params}", headers=self.headers)
        albums = data.get("result", {}).get("albums", []) or []
        candidates: list[ScrapeCandidate] = []
        for album in albums[:limit]:
            album_id = str(album.get("id") or "")
            if not album_id:
                continue
            detail = self._album_detail(album_id)
            candidate = self._candidate_from_album(detail or album)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _album_detail(self, album_id: str) -> dict[str, Any] | None:
        try:
            return fetch_json(f"https://music.163.com/api/album/{album_id}", headers=self.headers)
        except Exception:
            return None

    def _candidate_from_album(self, data: dict[str, Any]) -> ScrapeCandidate | None:
        album = data.get("album", data)
        album_id = str(album.get("id") or "")
        if not album_id:
            return None
        artist = None
        artists = album.get("artists") or []
        if artists:
            artist = artists[0].get("name")
        publish_time = album.get("publishTime")
        year = None
        release_date = None
        if publish_time:
            # Milliseconds since epoch.
            try:
                dt = time.strftime("%Y-%m-%d", time.localtime(int(publish_time) / 1000))
                year = dt[:4]
                release_date = dt
            except Exception:
                pass
        tracks: list[ScrapedTrack] = []
        for song in data.get("songs", []) or []:
            song_artists = song.get("artists") or song.get("ar") or []
            song_artist = song_artists[0].get("name") if song_artists else artist
            tracks.append(
                ScrapedTrack(
                    title=song.get("name"),
                    artist=song_artist,
                    tracknumber=str(song.get("no") or "") or None,
                    discnumber=str(song.get("cd") or "") or None,
                    source_id=str(song.get("id") or "") or None,
                    duration_ms=song.get("duration") or song.get("dt"),
                )
            )
        return ScrapeCandidate(
            provider=self.name,
            source_id=album_id,
            artist=artist,
            album=album.get("name"),
            year=year,
            release_date=release_date,
            release_type=album.get("type"),
            cover_url=album.get("picUrl") or album.get("blurPicUrl"),
            source_url=f"https://music.163.com/#/album?id={album_id}",
            tracks=tracks,
            warnings=["unofficial_api"],
        )


class PlannedProvider(AlbumProvider):
    def __init__(self, name: str, display_name: str, note: str):
        self.name = name
        self.display_name = display_name
        self.note = note
        self.implemented = False

    def search(self, local: AlbumMetadata, *, limit: int = 5) -> list[ScrapeCandidate]:
        return []


IMPLEMENTED_PROVIDERS: dict[str, AlbumProvider] = {
    "musicbrainz": MusicBrainzProvider(),
    "itunes": ITunesProvider(),
    "netease": NeteaseProvider(),
}

PLANNED_PROVIDERS: dict[str, AlbumProvider] = {
    "qmusic": PlannedProvider("qmusic", "QQ Music", "music-tag source; needs robust public/API adapter"),
    "kugou": PlannedProvider("kugou", "KuGou", "music-tag source; planned"),
    "kuwo": PlannedProvider("kuwo", "KuWo", "music-tag source; planned"),
    "migu": PlannedProvider("migu", "Migu", "music-tag source; planned"),
    "spotify": PlannedProvider("spotify", "Spotify", "requires credentials/client token strategy"),
    "acoustid": PlannedProvider("acoustid", "AcoustID", "requires AcoustID key and fpcalc/chromaprint"),
    "ximalaya": PlannedProvider("ximalaya", "Ximalaya", "music-tag source; useful for audiobooks/podcasts"),
    "smart_tag": PlannedProvider("smart_tag", "Smart Tag", "aggregation layer; our resolver will fill this role"),
}


def all_provider_info() -> list[dict[str, str | bool]]:
    rows = []
    for provider in {**IMPLEMENTED_PROVIDERS, **PLANNED_PROVIDERS}.values():
        rows.append(
            {
                "name": provider.name,
                "display_name": provider.display_name,
                "implemented": provider.implemented,
                "note": provider.note,
            }
        )
    return rows


def get_providers(names: list[str] | None = None) -> list[AlbumProvider]:
    if not names:
        names = list(IMPLEMENTED_PROVIDERS)
    providers: list[AlbumProvider] = []
    for name in names:
        key = name.strip().lower()
        if not key:
            continue
        provider = IMPLEMENTED_PROVIDERS.get(key)
        if provider:
            providers.append(provider)
    return providers


def alias_query_variants(local: AlbumMetadata) -> list[AlbumMetadata]:
    artists = local.artist_aliases or [local.artist]
    albums = local.album_aliases or [local.album]
    variants: list[AlbumMetadata] = []
    seen: set[tuple[str | None, str | None]] = {(local.artist, local.album)}
    for artist in artists:
        for album in albums:
            key = (artist or local.artist, album or local.album)
            if key in seen:
                continue
            seen.add(key)
            variants.append(replace(local, artist=key[0], album=key[1]))
    return variants


def scrape_candidates(
    local: AlbumMetadata,
    *,
    providers: list[AlbumProvider],
    limit_per_source: int,
    local_track_count: int = 0,
    local_track_durations_ms: list[int] | None = None,
) -> tuple[list[ScrapeCandidate], list[str]]:
    candidates: list[ScrapeCandidate] = []
    warnings: list[str] = []
    for provider in providers:
        rows: list[ScrapeCandidate] = []
        try:
            rows.extend(provider.search(local, limit=limit_per_source))
            best_primary_score = max(
                (
                    score_candidate(
                        local,
                        row,
                        local_track_count=local_track_count,
                        local_track_durations_ms=local_track_durations_ms,
                    )
                    for row in rows
                ),
                default=0.0,
            )
            if best_primary_score < ALIAS_QUERY_THRESHOLD:
                for variant in alias_query_variants(local):
                    rows.extend(provider.search(variant, limit=limit_per_source))
        except Exception as exc:
            warnings.append(f"{provider.name}: {exc}")
            continue

        seen_source_ids: set[str] = set()
        for row in rows:
            if row.source_id in seen_source_ids:
                continue
            seen_source_ids.add(row.source_id)
            max_duration_diff = duration_mismatch_ms(local_track_durations_ms, row)
            row_warnings = list(row.warnings)
            if local_track_count and row.tracks and len(row.tracks) != local_track_count:
                row_warnings.append(
                    f"track_count_mismatch:local={local_track_count}:remote={len(row.tracks)}"
                )
            if max_duration_diff is not None and max_duration_diff > 8_000:
                row_warnings.append(f"track_duration_mismatch:{max_duration_diff}ms")
            candidates.append(
                replace(
                    row,
                    score=score_candidate(
                        local,
                        row,
                        local_track_count=local_track_count,
                        local_track_durations_ms=local_track_durations_ms,
                    ),
                    warnings=row_warnings,
                )
            )
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates, warnings

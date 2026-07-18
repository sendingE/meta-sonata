from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from mutagen import File as MutagenFile

from .matching import has_live_words, text_similarity
from .models import AlbumPlan, TrackPlan
from .providers import DEFAULT_TIMEOUT


LYRICS_TAG_KEYS = ("lyrics", "unsyncedlyrics", "syncedlyrics")
LYRICS_MODE_CHOICES = ("prefer-synced", "synced", "plain", "both")
DEFAULT_LYRICS_MODE = "prefer-synced"
DEFAULT_LYRICS_SOURCES = "qmusic,netease,kugou,kuwo,migu"
MIN_LYRICS_SCORE = 0.72
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass(frozen=True)
class LyricsCandidate:
    source: str
    source_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: str | None = None
    tracknumber: str | None = None
    raw: dict[str, Any] | None = None
    score: float = 0.0


@dataclass(frozen=True)
class LyricsResult:
    provider: str
    source_id: str | None = None
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None
    instrumental: bool = False
    track_name: str | None = None
    artist_name: str | None = None
    album_name: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class LyricsEnrichmentReport:
    total: int = 0
    found: int = 0
    missing: int = 0
    skipped_existing: int = 0
    migrated_existing: int = 0
    instrumental: int = 0
    errors: int = 0

    def merge(self, other: "LyricsEnrichmentReport") -> "LyricsEnrichmentReport":
        return LyricsEnrichmentReport(
            total=self.total + other.total,
            found=self.found + other.found,
            missing=self.missing + other.missing,
            skipped_existing=self.skipped_existing + other.skipped_existing,
            migrated_existing=self.migrated_existing + other.migrated_existing,
            instrumental=self.instrumental + other.instrumental,
            errors=self.errors + other.errors,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "found": self.found,
            "missing": self.missing,
            "skipped_existing": self.skipped_existing,
            "migrated_existing": self.migrated_existing,
            "instrumental": self.instrumental,
            "errors": self.errors,
        }


class LyricsSource(Protocol):
    name: str

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        ...

    def fetch_lyric(self, source_id: str) -> str:
        ...


class LyricsProvider(Protocol):
    name: str

    def get_lyrics(
        self,
        *,
        artist_name: str,
        track_name: str,
        album_name: str | None = None,
        duration: int | None = None,
    ) -> LyricsResult | None:
        ...


class MusicTagLyricsProvider:
    name = "music-tag"

    def __init__(
        self,
        source_names: list[str] | None = None,
        *,
        limit_per_source: int = 5,
        min_score: float = MIN_LYRICS_SCORE,
    ):
        self.sources = get_lyrics_sources(source_names)
        self.limit_per_source = limit_per_source
        self.min_score = min_score

    def get_lyrics(
        self,
        *,
        artist_name: str,
        track_name: str,
        album_name: str | None = None,
        duration: int | None = None,
    ) -> LyricsResult | None:
        del duration
        ranked: list[tuple[LyricsSource, LyricsCandidate]] = []
        for source in self.sources:
            candidates = source.search(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name,
                limit=self.limit_per_source,
            )
            scored = [
                replace(
                    candidate,
                    score=score_lyrics_candidate(
                        track_name=track_name,
                        artist_name=artist_name,
                        album_name=album_name,
                        candidate=candidate,
                    ),
                )
                for candidate in candidates
            ]
            ranked.extend((source, candidate) for candidate in scored)

        ranked.sort(key=lambda item: item[1].score, reverse=True)
        for source, candidate in ranked:
            if candidate.score < self.min_score:
                break
            lyric = normalize_synced_lyrics(_clean_lyrics(source.fetch_lyric(candidate.source_id)))
            if not lyric:
                continue
            lyric_title = lrc_metadata(lyric, "ti")
            if lyric_title and text_similarity(track_name, lyric_title) < 0.62:
                continue
            return LyricsResult(
                provider=source.name,
                source_id=candidate.source_id,
                synced_lyrics=lyric,
                plain_lyrics=plain_from_lrc(lyric),
                track_name=candidate.title,
                artist_name=candidate.artist,
                album_name=candidate.album,
                score=candidate.score,
            )
        return None


class NeteaseLyricsSource:
    name = "netease"

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "http://music.163.com",
        "Host": "music.163.com",
    }

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        del album_name
        params = urllib.parse.urlencode(
            {
                "type": "1",
                "s": music_tag_keyword(track_name, artist_name),
                "limit": str(limit),
                "offset": "0",
            }
        )
        data = fetch_json(f"https://music.163.com/api/cloudsearch/pc?{params}", headers=self.headers)
        candidates: list[LyricsCandidate] = []
        for item in data.get("result", {}).get("songs", []) or []:
            source_id = str(item.get("id") or "")
            if not source_id:
                continue
            artists = ",".join(artist.get("name", "") for artist in item.get("ar", []) if artist.get("name"))
            album = item.get("al") or {}
            publish_time = item.get("publishTime")
            year = None
            if publish_time:
                try:
                    year = time.strftime("%Y", time.localtime(int(publish_time) / 1000))
                except Exception:
                    year = None
            candidates.append(
                LyricsCandidate(
                    source=self.name,
                    source_id=source_id,
                    title=item.get("name"),
                    artist=artists or None,
                    album=album.get("name"),
                    year=year,
                    tracknumber=str(item.get("no") or "") or None,
                    raw=item,
                )
            )
        return candidates

    def fetch_lyric(self, source_id: str) -> str:
        params = urllib.parse.urlencode({"id": source_id, "lv": -1, "kv": -1, "tv": -1})
        data = fetch_json(f"http://music.163.com/api/song/lyric?{params}", headers=self.headers)
        return ((data.get("lrc") or {}).get("lyric") or "").strip()


class QMusicLyricsSource:
    name = "qmusic"

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://y.qq.com/",
    }

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        del album_name
        payload = {
            "comm": {"ct": "19", "cv": "1859", "uin": "0"},
            "req": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "query": music_tag_keyword(track_name, artist_name),
                    "page_num": 1,
                    "num_per_page": limit,
                    "search_type": 0,
                },
            },
        }
        data = fetch_json(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            headers={**self.headers, "Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        songs = data.get("req", {}).get("data", {}).get("body", {}).get("song", {}).get("list", []) or []
        candidates: list[LyricsCandidate] = []
        for song in songs:
            source_id = str(song.get("mid") or "")
            if not source_id:
                continue
            album = song.get("album") or {}
            artists = ",".join(artist.get("name", "") for artist in song.get("singer", []) if artist.get("name"))
            candidates.append(
                LyricsCandidate(
                    source=self.name,
                    source_id=source_id,
                    title=song.get("title") or song.get("name"),
                    artist=artists or None,
                    album=album.get("name"),
                    raw=song,
                )
            )
        return candidates

    def fetch_lyric(self, source_id: str) -> str:
        params = urllib.parse.urlencode(
            {
                "g_tk": 5381,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "h5",
                "needNewCode": 1,
                "ct": 121,
                "cv": 0,
                "songmid": source_id,
            }
        )
        data = fetch_json(f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?{params}", headers=self.headers)
        encoded = data.get("lyric") or ""
        if not encoded:
            return ""
        return base64.b64decode(encoded).decode("utf-8", errors="replace").replace("&apos;", "'").strip()


class KugouLyricsSource:
    name = "kugou"

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.kugou.com/",
    }
    public_signature_key = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        del album_name
        timestamp = str(int(time.time() * 1000))
        params = {
            "bitrate": "0",
            "clienttime": timestamp,
            "clientver": "2000",
            "dfid": "-",
            "inputtype": "0",
            "iscorrection": "1",
            "isfuzzy": "0",
            "keyword": music_tag_keyword(track_name, artist_name),
            "mid": timestamp,
            "page": "1",
            "pagesize": str(limit),
            "platform": "WebFilter",
            "privilege_filter": "0",
            "srcappid": "2919",
            "tag": "em",
            "userid": "-1",
            "uuid": timestamp,
        }
        signature_base = (
            self.public_signature_key
            + "".join(f"{key}={params[key]}" for key in sorted(params))
            + self.public_signature_key
        )
        params["signature"] = hashlib.md5(signature_base.encode("utf-8")).hexdigest().upper()
        url = f"https://complexsearch.kugou.com/v2/search/song?{urllib.parse.urlencode(params)}"
        data = fetch_json(url, headers=self.headers)
        candidates: list[LyricsCandidate] = []
        for song in data.get("data", {}).get("lists", []) or []:
            source_id = str(song.get("FileHash") or "")
            if not source_id:
                continue
            candidates.append(
                LyricsCandidate(
                    source=self.name,
                    source_id=source_id,
                    title=strip_markup(song.get("SongName")),
                    artist=strip_markup(song.get("SingerName")),
                    album=strip_markup(song.get("AlbumName")),
                    raw=song,
                )
            )
        return candidates

    def fetch_lyric(self, source_id: str) -> str:
        url = f"http://m.kugou.com/app/i/krc.php?cmd=100&timelength=999999&hash={urllib.parse.quote(source_id)}"
        return fetch_text(url, headers=self.headers).strip()


class KuwoLyricsSource:
    name = "kuwo"

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "http://www.kuwo.cn/",
    }

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        del album_name
        params = {
            "all": music_tag_keyword(track_name, artist_name),
            "ft": "music",
            "newsearch": "1",
            "itemset": "web_2013",
            "client": "kt",
            "cluster": "0",
            "pn": "0",
            "rn": str(limit),
            "rformat": "json",
            "encoding": "utf8",
            "vipver": "MUSIC_9.0.2.0",
            "plat": "pc",
            "devid": "38668888",
            "show_copyright_off": "1",
            "pcmp4": "1",
            "vermerge": "1",
            "mobi": "1",
        }
        data = fetch_json(f"https://search.kuwo.cn/r.s?{urllib.parse.urlencode(params)}", headers=self.headers)
        candidates: list[LyricsCandidate] = []
        for song in data.get("abslist", []) or []:
            source_id = str(song.get("MUSICRID") or "").replace("MUSIC_", "") or str(song.get("DC_TARGETID") or "")
            if not source_id:
                continue
            candidates.append(
                LyricsCandidate(
                    source=self.name,
                    source_id=source_id,
                    title=song.get("SONGNAME") or song.get("NAME"),
                    artist=song.get("ARTIST"),
                    album=song.get("ALBUM"),
                    raw=song,
                )
            )
        return candidates

    def fetch_lyric(self, source_id: str) -> str:
        data = fetch_json(f"http://kuwo.cn/newh5/singles/songinfoandlrc?musicId={urllib.parse.quote(source_id)}", headers=self.headers)
        rows = (data.get("data") or {}).get("lrclist") or []
        lines = []
        for row in rows:
            lyric = str(row.get("lineLyric") or "").strip()
            if not lyric:
                continue
            try:
                seconds = float(row.get("time") or 0)
            except (TypeError, ValueError):
                seconds = 0.0
            lines.append(f"{format_lrc_time(seconds)}{lyric}")
        return "\n".join(lines)


class MiguLyricsSource:
    name = "migu"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Appid": "ce",
        "Channel": "014X031",
        "Deviceid": "40100A54-F4EA-4B1C-B420-1408A059CC8F",
        "Host": "c.musicapp.migu.cn",
        "Origin": "https://y.migu.cn",
        "Referer": "https://y.migu.cn/app/v4/zt/2022/music/index.html?newWebview=1&miguToken=null&appId=miguwap",
        "Subchannel": "014X031",
        "Ua": "Ios_migu",
        "User-Agent": USER_AGENT,
        "Version": "6.8.8",
    }

    def search(
        self,
        *,
        track_name: str,
        artist_name: str | None,
        album_name: str | None,
        limit: int,
    ) -> list[LyricsCandidate]:
        del album_name
        params = {
            "text": music_tag_keyword(track_name, artist_name),
            "pageNo": "1",
            "pageSize": str(limit),
            "isCopyright": "1",
            "sort": "1",
            "searchSwitch": '{"song":1,"album":0,"singer":0,"tagSong":1,"mvSong":0,"bestShow":1}',
        }
        data = fetch_json(
            f"https://c.musicapp.migu.cn/v1.0/content/search_all.do?{urllib.parse.urlencode(params)}",
            headers=self.headers,
        )
        candidates: list[LyricsCandidate] = []
        for song in (data.get("songResultData") or {}).get("result", []) or []:
            source_id = str(song.get("lyricUrl") or "")
            if not source_id:
                continue
            artists = ", ".join(item.get("name", "") for item in song.get("singers", []) if item.get("name"))
            albums = song.get("albums", []) or []
            candidates.append(
                LyricsCandidate(
                    source=self.name,
                    source_id=source_id,
                    title=song.get("name"),
                    artist=artists or None,
                    album=(albums[0].get("name") if albums else None),
                    year=(str(song.get("invalidateDate") or "")[:4] or None),
                    raw=song,
                )
            )
        return candidates

    def fetch_lyric(self, source_id: str) -> str:
        if not source_id.startswith(("http://", "https://")):
            return ""
        return fetch_text(source_id, headers={"User-Agent": USER_AGENT}).strip()


IMPLEMENTED_LYRICS_SOURCES: dict[str, type[LyricsSource]] = {
    "qmusic": QMusicLyricsSource,
    "netease": NeteaseLyricsSource,
    "kugou": KugouLyricsSource,
    "kuwo": KuwoLyricsSource,
    "migu": MiguLyricsSource,
}


def get_lyrics_sources(names: list[str] | None = None) -> list[LyricsSource]:
    if not names:
        names = [part.strip() for part in DEFAULT_LYRICS_SOURCES.split(",")]
    sources: list[LyricsSource] = []
    for name in names:
        source_cls = IMPLEMENTED_LYRICS_SOURCES.get(name.strip().lower())
        if source_cls:
            sources.append(source_cls())
    return sources


def get_lyrics_provider(source_names: str | list[str] | None = None) -> LyricsProvider:
    if source_names is None:
        names = None
    elif isinstance(source_names, str):
        names = [part.strip() for part in source_names.split(",") if part.strip()]
    else:
        names = source_names
    return MusicTagLyricsProvider(names)


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return json.loads(res.read().decode(charset, errors="replace"))


def fetch_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read().decode(charset, errors="replace")


def music_tag_keyword(track_name: str, artist_name: str | None) -> str:
    title = track_name.strip()
    artist = (artist_name or "").strip()
    if artist and artist not in title:
        return f"{title}-{artist}"
    return title


def score_lyrics_candidate(
    *,
    track_name: str,
    artist_name: str | None,
    album_name: str | None,
    candidate: LyricsCandidate,
) -> float:
    title_score = text_similarity(track_name, candidate.title)
    artist_score = text_similarity(artist_name, candidate.artist) if artist_name else 0.0
    album_score = text_similarity(album_name, candidate.album) if album_name and candidate.album else 0.0

    score = 0.58 * title_score
    if artist_name:
        score += 0.24 * artist_score
    else:
        score += 0.12
    if album_name and candidate.album:
        score += 0.18 * album_score
    elif album_name:
        score += 0.04
    else:
        score += 0.10

    local_live = has_live_words(track_name) or has_live_words(album_name)
    candidate_live = has_live_words(candidate.title) or has_live_words(candidate.album)
    if candidate_live and not local_live:
        score -= 0.22
    if title_score < 0.62:
        score -= 0.18
    if artist_name and candidate.artist and artist_score < 0.45:
        score -= 0.10
    if album_name and candidate.album and album_score < 0.35:
        score -= 0.08
    return max(0.0, min(1.0, score))


def track_duration_seconds(path: Path) -> int | None:
    try:
        audio = MutagenFile(str(path), easy=False)
    except Exception:
        audio = None
    info = getattr(audio, "info", None)
    length = getattr(info, "length", None)
    if length is None:
        return None
    try:
        return int(round(float(length)))
    except (TypeError, ValueError):
        return None


def has_embedded_lyrics(path: Path) -> bool:
    try:
        audio = MutagenFile(str(path), easy=False)
    except Exception:
        return False
    if audio is None:
        return False
    tags = getattr(audio, "tags", None) or audio
    for key in LYRICS_TAG_KEYS:
        try:
            values = tags.get(key) or tags.get(key.upper())
        except Exception:
            values = None
        if values:
            return True
    return False


def embedded_lyrics(path: Path) -> dict[str, str]:
    try:
        audio = MutagenFile(str(path), easy=False)
    except Exception:
        return {}
    if audio is None:
        return {}
    tags = getattr(audio, "tags", None) or audio
    values: dict[str, str] = {}
    for key in LYRICS_TAG_KEYS:
        try:
            rows = tags.get(key) or tags.get(key.upper())
        except Exception:
            rows = None
        if rows:
            values[key] = str(rows[0])
    return values


def has_lrc_timestamps(value: str | None) -> bool:
    return bool(value and re.search(r"(?m)^\s*\[\d+:\d{2}(?:[.:]\d{1,3})?\]", value))


def lyrics_tags(result: LyricsResult, *, mode: str = DEFAULT_LYRICS_MODE) -> dict[str, str]:
    if mode not in LYRICS_MODE_CHOICES:
        raise ValueError(f"unsupported lyrics mode: {mode}")

    tags: dict[str, str] = {}
    want_synced = mode in {"prefer-synced", "synced", "both"}
    want_plain = mode in {"plain", "both"}
    if mode == "prefer-synced" and not result.synced_lyrics:
        want_plain = True

    if want_synced and result.synced_lyrics:
        tags["lyrics"] = result.synced_lyrics
        tags["syncedlyrics"] = result.synced_lyrics
    if want_plain and result.plain_lyrics:
        tags.setdefault("lyrics", result.plain_lyrics)
        tags["unsyncedlyrics"] = result.plain_lyrics
    if result.source_id and tags:
        tags["lyrics_source"] = f"{result.provider}:{result.source_id}"
    if result.score and tags:
        tags["lyrics_score"] = f"{result.score:.3f}"
    return tags


def enrich_album_plan_with_lyrics(
    plan: AlbumPlan,
    *,
    provider_name: str = DEFAULT_LYRICS_SOURCES,
    provider: LyricsProvider | None = None,
    mode: str = DEFAULT_LYRICS_MODE,
    overwrite: bool = False,
    request_delay: float = 0.15,
) -> tuple[AlbumPlan, LyricsEnrichmentReport]:
    provider = provider or get_lyrics_provider(provider_name)
    report = LyricsEnrichmentReport(total=len(plan.tracks))
    enriched_tracks: list[TrackPlan] = []

    for track in plan.tracks:
        tags = dict(track.tags)
        warnings = list(track.warnings)

        if not overwrite:
            existing_lyrics = embedded_lyrics(track.path)
            synced_mode = mode in {"prefer-synced", "synced", "both"}
            generic_lyrics = existing_lyrics.get("lyrics")
            if (
                synced_mode
                and not existing_lyrics.get("syncedlyrics")
                and has_lrc_timestamps(generic_lyrics)
            ):
                tags["syncedlyrics"] = generic_lyrics
                report = replace(report, migrated_existing=report.migrated_existing + 1)
                enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
                continue
            if existing_lyrics:
                report = replace(report, skipped_existing=report.skipped_existing + 1)
                enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
                continue

        track_name = tags.get("title")
        artist_name = tags.get("artist") or plan.metadata.artist
        album_name = tags.get("album") or plan.metadata.album
        if not track_name or not artist_name:
            warnings.append("lyrics_missing_title_or_artist")
            report = replace(report, missing=report.missing + 1)
            enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
            continue

        try:
            duration = track_duration_seconds(track.path)
            query_variants = [(artist_name, album_name)]
            alias_artists = plan.metadata.artist_aliases or [artist_name]
            alias_albums = plan.metadata.album_aliases or [album_name]
            for alias_artist in alias_artists:
                for alias_album in alias_albums:
                    variant = (alias_artist or artist_name, alias_album or album_name)
                    if variant not in query_variants:
                        query_variants.append(variant)

            results: list[LyricsResult] = []
            for query_artist, query_album in query_variants:
                candidate_result = provider.get_lyrics(
                    artist_name=query_artist,
                    track_name=track_name,
                    album_name=query_album,
                    duration=duration,
                )
                if candidate_result is not None:
                    results.append(candidate_result)
                    if candidate_result.score >= 0.995:
                        break
            result = max(results, key=lambda item: item.score) if results else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            warnings.append(f"lyrics_error:{provider.name}:{exc}")
            report = replace(report, errors=report.errors + 1)
            enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
            continue
        except Exception as exc:
            warnings.append(f"lyrics_error:{provider.name}:{exc}")
            report = replace(report, errors=report.errors + 1)
            enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
            continue

        if result is None:
            warnings.append(f"lyrics_not_found:{provider.name}")
            report = replace(report, missing=report.missing + 1)
            enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
            if request_delay:
                time.sleep(request_delay)
            continue

        if result.instrumental and not result.plain_lyrics and not result.synced_lyrics:
            warnings.append(f"lyrics_instrumental:{result.provider}")
            report = replace(report, instrumental=report.instrumental + 1)
            enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
            if request_delay:
                time.sleep(request_delay)
            continue

        lyric_tags = lyrics_tags(result, mode=mode)
        if lyric_tags:
            tags.update(lyric_tags)
            report = replace(report, found=report.found + 1)
        else:
            warnings.append(f"lyrics_no_requested_format:{result.provider}")
            report = replace(report, missing=report.missing + 1)

        enriched_tracks.append(replace(track, tags=tags, warnings=warnings))
        if request_delay:
            time.sleep(request_delay)

    return replace(plan, tracks=enriched_tracks), report


def plain_from_lrc(value: str | None) -> str | None:
    if not value:
        return None
    lines = []
    for line in value.splitlines():
        stripped = re.sub(r"^\s*(?:\[[^\]]+\])+", "", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines) or None


def lrc_metadata(value: str | None, key: str) -> str | None:
    if not value:
        return None
    match = re.search(rf"^\[{re.escape(key)}:(.*?)\]\s*$", value, flags=re.I | re.M)
    if not match:
        return None
    return match.group(1).strip() or None


def normalize_synced_lyrics(value: str | None) -> str | None:
    if not value:
        return None
    untimed: list[str] = []
    timed: list[tuple[float, int, str]] = []
    for index, line in enumerate(value.splitlines()):
        match = re.match(r"^\s*\[(\d+):(\d{2})(?:[.:](\d{2,3}))?\]", line)
        if not match:
            untimed.append(line)
            continue
        fraction_text = match.group(3) or ""
        fraction = int(fraction_text or 0) / (1000 if len(fraction_text) == 3 else 100)
        seconds = int(match.group(1)) * 60 + int(match.group(2)) + fraction
        timed.append((seconds, index, line))
    timed.sort(key=lambda item: (item[0], item[1]))
    return "\n".join([*untimed, *(line for _, _, line in timed)]).strip() or None


def format_lrc_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    sec = seconds - minutes * 60
    return f"[{minutes:02d}:{sec:05.2f}]"


def strip_markup(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip() or None


def _clean_lyrics(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\ufeff", "").strip()
    return cleaned or None

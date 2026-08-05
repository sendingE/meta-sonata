from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .app_paths import default_api_cache_path


DEFAULT_TIMEOUT = 8
USER_AGENT = f"meta-sonata/{__version__} (https://github.com/sendingE/meta-sonata)"
MUSICBRAINZ_MIN_INTERVAL = 1.0


class ExternalServiceError(RuntimeError):
    def __init__(self, service: str, cause: BaseException) -> None:
        super().__init__(f"{service} unavailable ({cause.__class__.__name__})")
        self.service = service
        self.cause = cause


class RateLimiter:
    """Serialize calls and enforce a minimum start-to-start interval."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._sleeper = sleeper
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            delay = self._next_allowed - now
            if delay > 0:
                self._sleeper(delay)
                now = self._clock()
            self._next_allowed = max(now, self._next_allowed) + self.min_interval


# All clients in one process share the same MusicBrainz budget.  Tests may
# inject an isolated limiter, but there is no production/test bypass switch.
_GLOBAL_MUSICBRAINZ_LIMITER = RateLimiter(MUSICBRAINZ_MIN_INTERVAL)


@dataclass(frozen=True)
class CachedResponse:
    body: bytes
    content_type: str | None
    expired: bool


class ResponseCache:
    """Disposable SQLite cache. Cache failures never fail a provider request."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_api_cache_path()).expanduser()
        self._initialized = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=2.0)
        connection.execute("PRAGMA busy_timeout = 2000")
        return connection

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS responses (
                        cache_key TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        body BLOB NOT NULL,
                        content_type TEXT,
                        fetched_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
            self._initialized = True

    def get(self, cache_key: str, *, allow_expired: bool = False) -> CachedResponse | None:
        try:
            self._initialize()
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT body, content_type, expires_at FROM responses WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
            if not row:
                return None
            expired = float(row[2]) <= time.time()
            if expired and not allow_expired:
                return None
            return CachedResponse(bytes(row[0]), row[1], expired)
        except (OSError, sqlite3.Error):
            return None

    def set(
        self,
        cache_key: str,
        *,
        url: str,
        body: bytes,
        content_type: str | None,
        ttl: float,
    ) -> None:
        try:
            self._initialize()
            now = time.time()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO responses(cache_key, url, body, content_type, fetched_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        url = excluded.url,
                        body = excluded.body,
                        content_type = excluded.content_type,
                        fetched_at = excluded.fetched_at,
                        expires_at = excluded.expires_at
                    """,
                    (cache_key, url, body, content_type, now, now + max(0.0, ttl)),
                )
        except (OSError, sqlite3.Error):
            return

    def delete(self, cache_key: str) -> None:
        try:
            self._initialize()
            with self._connect() as connection:
                connection.execute("DELETE FROM responses WHERE cache_key = ?", (cache_key,))
        except (OSError, sqlite3.Error):
            return


@dataclass(frozen=True)
class NetworkResponse:
    body: bytes
    content_type: str | None


class NetworkClient:
    def __init__(
        self,
        *,
        cache: ResponseCache | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        musicbrainz_limiter: RateLimiter | None = None,
    ) -> None:
        self.cache = cache or ResponseCache()
        self._opener = opener
        self._musicbrainz_limiter = (
            musicbrainz_limiter
            if musicbrainz_limiter is not None
            else _GLOBAL_MUSICBRAINZ_LIMITER
        )

    @staticmethod
    def _service(url: str) -> str:
        return (urllib.parse.urlparse(url).hostname or "third-party service").lower()

    @staticmethod
    def _is_musicbrainz(url: str) -> bool:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return host == "musicbrainz.org" or host.endswith(".musicbrainz.org")

    @staticmethod
    def _cache_key(url: str, data: bytes | None, headers: dict[str, str]) -> str:
        safe_headers = {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() not in {"authorization", "cookie", "set-cookie"}
        }
        payload = json.dumps(
            {
                "url": url,
                "body_sha256": hashlib.sha256(data or b"").hexdigest(),
                "headers": sorted(safe_headers.items()),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _default_ttl(url: str) -> float:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host == "musicbrainz.org" or host.endswith(".musicbrainz.org"):
            return 7 * 24 * 60 * 60
        if host == "coverartarchive.org" or host.endswith(".coverartarchive.org"):
            return 30 * 24 * 60 * 60
        return 24 * 60 * 60

    @staticmethod
    def _content_type(headers: Any) -> str | None:
        try:
            return headers.get("Content-Type")
        except Exception:
            return None

    def _request(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        data: bytes | None,
        timeout: int,
    ) -> NetworkResponse:
        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        if self._is_musicbrainz(url):
            self._musicbrainz_limiter.wait()
        request = urllib.request.Request(url, data=data, headers=request_headers)
        try:
            with self._opener(request, timeout=timeout) as response:
                return NetworkResponse(
                    body=response.read(),
                    content_type=self._content_type(response.headers),
                )
        except Exception as exc:
            raise ExternalServiceError(self._service(url), exc) from exc

    def fetch_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        cache_ttl: float | None = None,
    ) -> NetworkResponse:
        request_headers = dict(headers or {})
        cache_key = self._cache_key(url, data, request_headers)
        cached = self.cache.get(cache_key)
        if cached:
            return NetworkResponse(cached.body, cached.content_type)
        try:
            response = self._request(
                url,
                headers=request_headers,
                data=data,
                timeout=timeout,
            )
        except ExternalServiceError:
            stale = self.cache.get(cache_key, allow_expired=True)
            if stale:
                return NetworkResponse(stale.body, stale.content_type)
            raise
        self.cache.set(
            cache_key,
            url=url,
            body=response.body,
            content_type=response.content_type,
            ttl=self._default_ttl(url) if cache_ttl is None else cache_ttl,
        )
        return response

    def fetch_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        cache_ttl: float | None = None,
    ) -> Any:
        request_headers = {"Accept": "application/json", **(headers or {})}
        response = self.fetch_bytes(
            url,
            headers=request_headers,
            data=data,
            timeout=timeout,
            cache_ttl=cache_ttl,
        )
        charset = "utf-8"
        if response.content_type:
            message = Message()
            message["content-type"] = response.content_type
            charset = message.get_content_charset() or "utf-8"
        try:
            return json.loads(response.body.decode(charset, errors="replace"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            cache_key = self._cache_key(url, data, request_headers)
            self.cache.delete(cache_key)
            raise ExternalServiceError(self._service(url), exc) from exc

    def fetch_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        cache_ttl: float | None = None,
    ) -> str:
        response = self.fetch_bytes(
            url,
            headers=headers,
            timeout=timeout,
            cache_ttl=cache_ttl,
        )
        charset = "utf-8"
        if response.content_type:
            message = Message()
            message["content-type"] = response.content_type
            charset = message.get_content_charset() or "utf-8"
        return response.body.decode(charset, errors="replace")


_default_client = NetworkClient()


def fetch_json(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    cache_ttl: float | None = None,
) -> Any:
    return _default_client.fetch_json(
        url,
        timeout=timeout,
        headers=headers,
        data=data,
        cache_ttl=cache_ttl,
    )


def fetch_text(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    cache_ttl: float | None = None,
) -> str:
    return _default_client.fetch_text(
        url,
        timeout=timeout,
        headers=headers,
        cache_ttl=cache_ttl,
    )


def fetch_bytes(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    cache_ttl: float | None = None,
) -> NetworkResponse:
    return _default_client.fetch_bytes(
        url,
        timeout=timeout,
        headers=headers,
        cache_ttl=cache_ttl,
    )

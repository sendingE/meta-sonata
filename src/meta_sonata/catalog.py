from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from mutagen import File as MutagenFile

from .app_paths import default_catalog_path
from .models import AUDIO_EXTENSIONS
from .scanner import is_ignored_name


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalized_tags(path: Path) -> dict[str, list[str]]:
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None
    if audio is None:
        return {}
    tags = getattr(audio, "tags", None) or audio
    try:
        rows = tags.items()
    except Exception:
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in rows:
        values = value if isinstance(value, list) else [value]
        rendered = [str(item).strip() for item in values if str(item).strip()]
        if rendered:
            normalized[str(key).lower()] = rendered
    return normalized


def _first(tags: dict[str, list[str]], key: str) -> str | None:
    values = tags.get(key.lower()) or []
    return values[0] if values else None


def _external_ids(tags: dict[str, list[str]], key: str) -> list[str]:
    ids: list[str] = []
    for value in tags.get(key.lower()) or []:
        for part in str(value).replace(";", "\x00").split("\x00"):
            candidate = part.strip()
            if candidate and candidate not in ids:
                ids.append(candidate)
    return ids


class CatalogDatabase:
    """Durable local catalog; audio files remain the portable metadata source."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_catalog_path()).expanduser()
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            with self._connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS library_roots (
                        id TEXT PRIMARY KEY,
                        path TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        volume_id TEXT,
                        bookmark BLOB,
                        created_at TEXT NOT NULL,
                        last_scanned_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        library_id TEXT NOT NULL REFERENCES library_roots(id) ON DELETE CASCADE,
                        relative_path TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        suffix TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        last_seen_token TEXT,
                        indexed_at TEXT NOT NULL,
                        UNIQUE(library_id, relative_path)
                    );

                    CREATE TABLE IF NOT EXISTS entities (
                        id TEXT PRIMARY KEY,
                        entity_type TEXT NOT NULL,
                        canonical_name TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS external_ids (
                        entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        provider TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        PRIMARY KEY(provider, entity_type, external_id)
                    );

                    CREATE TABLE IF NOT EXISTS aliases (
                        entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        locale TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(entity_id, name, locale, source)
                    );

                    CREATE TABLE IF NOT EXISTS file_entities (
                        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                        entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 1.0,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(file_id, entity_id, role, status)
                    );

                    CREATE TABLE IF NOT EXISTS decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
                        field TEXT NOT NULL,
                        original_value TEXT,
                        proposed_value TEXT,
                        decision TEXT NOT NULL CHECK(decision IN ('accepted', 'rejected')),
                        provider TEXT,
                        external_id TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS files_library_path
                        ON files(library_id, relative_path);
                    CREATE INDEX IF NOT EXISTS aliases_name
                        ON aliases(name);
                    CREATE INDEX IF NOT EXISTS file_entities_file
                        ON file_entities(file_id);
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _now()),
                )
            self._initialized = True

    def register_library(self, root: Path) -> str:
        self.initialize()
        root = root.expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        root_id = uuid.uuid5(uuid.NAMESPACE_URL, f"meta-sonata:{root}").hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO library_roots(id, path, display_name, volume_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    display_name = excluded.display_name,
                    volume_id = excluded.volume_id
                """,
                (root_id, str(root), root.name or str(root), str(root.stat().st_dev), _now()),
            )
            row = connection.execute(
                "SELECT id FROM library_roots WHERE path = ?", (str(root),)
            ).fetchone()
        assert row is not None
        return str(row[0])

    def _entity_for_external_id(
        self,
        connection: sqlite3.Connection,
        *,
        provider: str,
        entity_type: str,
        external_id: str,
        canonical_name: str | None,
    ) -> str:
        row = connection.execute(
            """
            SELECT entity_id FROM external_ids
            WHERE provider = ? AND entity_type = ? AND external_id = ?
            """,
            (provider, entity_type, external_id),
        ).fetchone()
        if row:
            entity_id = str(row[0])
            if canonical_name:
                connection.execute(
                    "UPDATE entities SET canonical_name = COALESCE(canonical_name, ?) WHERE id = ?",
                    (canonical_name, entity_id),
                )
            return entity_id
        entity_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO entities(id, entity_type, canonical_name, created_at) VALUES (?, ?, ?, ?)",
            (entity_id, entity_type, canonical_name, _now()),
        )
        connection.execute(
            """
            INSERT INTO external_ids(entity_id, provider, entity_type, external_id)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, provider, entity_type, external_id),
        )
        return entity_id

    def _link_embedded_entities(
        self,
        connection: sqlite3.Connection,
        file_id: int,
        tags: dict[str, list[str]],
    ) -> None:
        connection.execute(
            "DELETE FROM file_entities WHERE file_id = ? AND status = 'embedded'",
            (file_id,),
        )
        mappings = (
            ("musicbrainz_artistid", "artist", "track_artist", _first(tags, "artist")),
            (
                "musicbrainz_albumartistid",
                "artist",
                "release_artist",
                _first(tags, "albumartist"),
            ),
            ("musicbrainz_recordingid", "recording", "recording", _first(tags, "title")),
            ("musicbrainz_albumid", "release", "release", _first(tags, "album")),
            ("musicbrainz_releasegroupid", "release_group", "release_group", _first(tags, "album")),
            ("musicbrainz_trackid", "track", "release_track", _first(tags, "title")),
        )
        for tag_key, entity_type, role, display_name in mappings:
            for external_id in _external_ids(tags, tag_key):
                entity_id = self._entity_for_external_id(
                    connection,
                    provider="musicbrainz",
                    entity_type=entity_type,
                    external_id=external_id,
                    canonical_name=display_name,
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO file_entities(
                        file_id, entity_id, role, confidence, status, source, updated_at
                    ) VALUES (?, ?, ?, 1.0, 'embedded', 'file_tag', ?)
                    """,
                    (file_id, entity_id, role, _now()),
                )
                if display_name:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO aliases(entity_id, name, locale, source, created_at)
                        VALUES (?, ?, '', 'file_tag', ?)
                        """,
                        (entity_id, display_name, _now()),
                    )

    def index_audio_file(
        self,
        root: Path,
        path: Path,
        *,
        tags: dict[str, list[str]] | None = None,
        seen_token: str | None = None,
    ) -> int:
        self.initialize()
        root = root.expanduser().resolve()
        path = path.expanduser().resolve()
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"not an audio file: {path}")
        library_id = self.register_library(root)
        stat = path.stat()
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT id, size, mtime_ns FROM files
                WHERE library_id = ? AND relative_path = ?
                """,
                (library_id, relative),
            ).fetchone()
            if (
                tags is None
                and existing
                and int(existing["size"]) == stat.st_size
                and int(existing["mtime_ns"]) == stat.st_mtime_ns
            ):
                if seen_token is not None:
                    connection.execute(
                        "UPDATE files SET last_seen_token = ? WHERE id = ?",
                        (seen_token, int(existing["id"])),
                    )
                return int(existing["id"])

            normalized = tags if tags is not None else _normalized_tags(path)
            connection.execute(
                """
                INSERT INTO files(
                    library_id, relative_path, size, mtime_ns, suffix,
                    tags_json, last_seen_token, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(library_id, relative_path) DO UPDATE SET
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    suffix = excluded.suffix,
                    tags_json = excluded.tags_json,
                    last_seen_token = COALESCE(excluded.last_seen_token, files.last_seen_token),
                    indexed_at = excluded.indexed_at
                """,
                (
                    library_id,
                    relative,
                    stat.st_size,
                    stat.st_mtime_ns,
                    path.suffix.lower(),
                    json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
                    seen_token,
                    _now(),
                ),
            )
            row = connection.execute(
                "SELECT id FROM files WHERE library_id = ? AND relative_path = ?",
                (library_id, relative),
            ).fetchone()
            assert row is not None
            file_id = int(row[0])
            self._link_embedded_entities(connection, file_id, normalized)
            return file_id

    def sync_library(self, root: Path) -> dict[str, int]:
        root = root.expanduser().resolve()
        library_id = self.register_library(root)
        token = uuid.uuid4().hex
        indexed = skipped = traversal_errors = 0

        def on_error(_error: OSError) -> None:
            nonlocal traversal_errors
            traversal_errors += 1

        for directory, names, files in os.walk(root, followlinks=False, onerror=on_error):
            names[:] = [
                name
                for name in names
                if not is_ignored_name(name) and not (Path(directory) / name).is_symlink()
            ]
            for name in files:
                path = Path(directory) / name
                if is_ignored_name(name) or path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                try:
                    self.index_audio_file(root, path, seen_token=token)
                    indexed += 1
                except (OSError, ValueError, sqlite3.Error):
                    skipped += 1

        with self._connection() as connection:
            removed = 0
            if traversal_errors == 0:
                cursor = connection.execute(
                    """
                    DELETE FROM files
                    WHERE library_id = ? AND COALESCE(last_seen_token, '') != ?
                    """,
                    (library_id, token),
                )
                removed = max(0, cursor.rowcount)
            connection.execute(
                "UPDATE library_roots SET last_scanned_at = ? WHERE id = ?",
                (_now(), library_id),
            )
        return {
            "indexed": indexed,
            "skipped": skipped,
            "removed": removed,
            "traversal_errors": traversal_errors,
        }

    def record_match(
        self,
        root: Path,
        path: Path,
        *,
        provider: str,
        entity_type: str,
        external_id: str,
        display_name: str | None,
        confidence: float,
        status: str = "suggested",
    ) -> None:
        if status not in {"suggested", "confirmed", "rejected"}:
            raise ValueError(f"unsupported match status: {status}")
        file_id = self.index_audio_file(root, path)
        with self._connection() as connection:
            entity_id = self._entity_for_external_id(
                connection,
                provider=provider,
                entity_type=entity_type,
                external_id=external_id,
                canonical_name=display_name,
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO file_entities(
                    file_id, entity_id, role, confidence, status, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    entity_id,
                    entity_type,
                    max(0.0, min(1.0, confidence)),
                    status,
                    provider,
                    _now(),
                ),
            )

    def record_decision(
        self,
        root: Path,
        path: Path,
        *,
        field: str,
        original_value: str | None,
        proposed_value: str | None,
        decision: str,
        provider: str | None = None,
        external_id: str | None = None,
    ) -> None:
        if decision not in {"accepted", "rejected"}:
            raise ValueError(f"unsupported decision: {decision}")
        file_id = self.index_audio_file(root, path)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO decisions(
                    file_id, field, original_value, proposed_value,
                    decision, provider, external_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    field,
                    original_value,
                    proposed_value,
                    decision,
                    provider,
                    external_id,
                    _now(),
                ),
            )

    def stats(self) -> dict[str, int]:
        self.initialize()
        with self._connection() as connection:
            return {
                "libraries": int(connection.execute("SELECT COUNT(*) FROM library_roots").fetchone()[0]),
                "files": int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
                "entities": int(connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]),
                "decisions": int(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]),
            }


def try_default_catalog() -> CatalogDatabase | None:
    try:
        catalog = CatalogDatabase()
        catalog.initialize()
        return catalog
    except (OSError, sqlite3.Error):
        return None


def sync_library_in_background(catalog: CatalogDatabase, root: Path) -> threading.Thread:
    def run() -> None:
        try:
            catalog.sync_library(root)
        except (OSError, sqlite3.Error, ValueError):
            return

    thread = threading.Thread(target=run, name="meta-sonata-catalog", daemon=True)
    thread.start()
    return thread

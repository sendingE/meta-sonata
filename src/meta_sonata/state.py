from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from platformdirs import user_state_path

from .scanner import is_ignored_name


PIPELINE_MARKER_NAME = "_pipeline.done"
STATE_DIR_ENV = "META_SONATA_STATE_DIR"


def album_signature(album: Path) -> str:
    """Fingerprint album files while ignoring pipeline/tool marker files."""
    h = hashlib.sha256()
    for path in sorted(album.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(album)
        except ValueError:
            continue
        if any(is_ignored_name(part) for part in rel.parts):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        h.update(f"{rel.as_posix()}|{st.st_size}|{int(st.st_mtime)}\n".encode("utf-8"))
    return h.hexdigest()


def default_state_dir() -> Path:
    configured = os.environ.get(STATE_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return user_state_path("meta-sonata", appauthor=False)


def album_state_key(album: Path) -> str:
    resolved = str(album.expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def state_path(album: Path, state_dir: Path | None = None) -> Path:
    root = state_dir or default_state_dir()
    return root / f"{album_state_key(album)}.json"


def pipeline_marker_path(album: Path, marker_name: str = PIPELINE_MARKER_NAME) -> Path:
    return album / marker_name


def read_state(album: Path, state_dir: Path | None = None) -> dict[str, Any] | None:
    path = state_path(album, state_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def has_current_state(album: Path, signature: str | None = None, state_dir: Path | None = None) -> bool:
    data = read_state(album, state_dir)
    if not data:
        return False
    current = signature or album_signature(album)
    return data.get("album_signature") == current and data.get("album_path") == str(
        album.expanduser().resolve(strict=False)
    )


def has_pipeline_marker_since(
    album: Path,
    since_epoch: float,
    *,
    marker_name: str = PIPELINE_MARKER_NAME,
) -> bool:
    path = pipeline_marker_path(album, marker_name)
    if not path.exists():
        return False
    try:
        return path.stat().st_mtime >= since_epoch
    except OSError:
        return False


def write_state(album: Path, payload: dict[str, Any], state_dir: Path | None = None) -> None:
    path = state_path(album, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tool": "meta-sonata",
        "marked_at": datetime.now().isoformat(timespec="seconds"),
        "album_path": str(album.expanduser().resolve(strict=False)),
        **payload,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

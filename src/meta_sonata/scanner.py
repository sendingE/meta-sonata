from __future__ import annotations

import re
from pathlib import Path

from .models import AUDIO_EXTENSIONS, COVER_FILENAMES, AlbumScan


DISC_DIR_RE = re.compile(r"^(?:disc|disk|cd)\s*[-_ ]?\s*\d+$", re.I)
DEFAULT_SCAN_DEPTH = 3


def is_ignored_name(name: str) -> bool:
    return (
        name == ".DS_Store"
        or name.startswith("._")
        or name.startswith(".")
        or name.startswith("_pipeline.")
        or name.startswith("_musicinfo.")
    )


def is_audio_file(path: Path) -> bool:
    return path.is_file() and not is_ignored_name(path.name) and path.suffix.lower() in AUDIO_EXTENSIONS


def _is_cover_file(path: Path) -> bool:
    return path.is_file() and path.name.lower() in COVER_FILENAMES


def _safe_files(root: Path) -> list[Path]:
    files: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        for path in _safe_children(current):
            if path.is_symlink():
                continue
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                files.append(path)
    return files


def _safe_children(path: Path) -> list[Path]:
    try:
        return sorted(child for child in path.iterdir() if not is_ignored_name(child.name))
    except OSError:
        return []


def looks_like_disc_dir(path: Path) -> bool:
    return bool(DISC_DIR_RE.match(path.name.strip()))


def _has_direct_audio(path: Path) -> bool:
    return any(is_audio_file(child) for child in _safe_children(path))


def _has_only_disc_audio_children(path: Path) -> bool:
    child_dirs = [
        child
        for child in _safe_children(path)
        if child.is_dir() and not child.is_symlink()
    ]
    disc_dirs = [child for child in child_dirs if looks_like_disc_dir(child)]
    if not disc_dirs:
        return False
    return any(any(is_audio_file(candidate) for candidate in _safe_files(child)) for child in disc_dirs)


def _album_files(album_dir: Path) -> list[Path]:
    files = [child for child in _safe_children(album_dir) if child.is_file()]
    for child in _safe_children(album_dir):
        if child.is_dir() and not child.is_symlink() and looks_like_disc_dir(child):
            files.extend(_safe_files(child))
    return files


def scan_album(album_dir: Path) -> AlbumScan:
    files = _album_files(album_dir)
    audio_files = sorted(p for p in files if is_audio_file(p))
    cover_files = sorted(p for p in files if _is_cover_file(p))
    cue_files = sorted(p for p in files if p.suffix.lower() == ".cue")
    log_files = sorted(p for p in files if p.suffix.lower() == ".log")
    return AlbumScan(
        path=album_dir,
        audio_files=audio_files,
        cover_file=cover_files[0] if cover_files else None,
        cue_files=cue_files,
        log_files=log_files,
    )


def discover_album_dirs(root: Path, *, max_depth: int | None = DEFAULT_SCAN_DEPTH) -> list[Path]:
    root = root.expanduser()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    if max_depth is not None and max_depth < 0:
        raise ValueError("max_depth must be zero or greater, or None for unlimited recursion")

    albums: list[Path] = []
    pending: list[tuple[Path, int]] = [(root, 0)]
    visited: set[Path] = set()
    while pending:
        current, depth = pending.pop(0)
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in visited:
            continue
        visited.add(resolved)

        direct_audio = _has_direct_audio(current)
        disc_album = not direct_audio and _has_only_disc_audio_children(current)
        if direct_audio or disc_album:
            albums.append(current)

        if max_depth is not None and depth >= max_depth:
            continue
        for child in _safe_children(current):
            if not child.is_dir() or child.is_symlink():
                continue
            if (direct_audio or disc_album) and looks_like_disc_dir(child):
                continue
            pending.append((child, depth + 1))

    return sorted(albums)


def scan_root(root: Path, *, max_depth: int | None = DEFAULT_SCAN_DEPTH) -> list[AlbumScan]:
    return [scan_album(path) for path in discover_album_dirs(root, max_depth=max_depth)]

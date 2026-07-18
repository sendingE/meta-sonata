from __future__ import annotations

import mimetypes
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture

from .models import AlbumPlan, ApplyResult
from .safety import assert_write_allowed


SUPPORTED_WRITE_EXTENSIONS = {".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus"}


def _mime_for_cover(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "image/jpeg"


def _write_flac(path: Path, tags: dict[str, str], cover_file: Path | None, replace_cover: bool) -> bool:
    audio = FLAC(str(path))
    changed = False
    for key, value in tags.items():
        current = audio.get(key, [""])[0]
        if current != value:
            audio[key] = [value]
            changed = True

    if cover_file:
        has_picture = bool(audio.pictures)
        if replace_cover or not has_picture:
            if replace_cover:
                audio.clear_pictures()
            picture = Picture()
            picture.type = 3
            picture.mime = _mime_for_cover(cover_file)
            picture.desc = "Cover"
            picture.data = cover_file.read_bytes()
            audio.add_picture(picture)
            changed = True

    if changed:
        audio.save()
    return changed


def _write_easy(path: Path, tags: dict[str, str]) -> bool:
    audio = MutagenFile(str(path), easy=True)
    if audio is None:
        raise ValueError("mutagen could not open file")

    changed = False
    for key, value in tags.items():
        try:
            current = audio.get(key, [""])[0]
            if current != value:
                audio[key] = [value]
                changed = True
        except Exception:
            # Easy tags differ by container; ignore keys unsupported by this file.
            continue
    if changed:
        audio.save()
    return changed


def write_track(path: Path, tags: dict[str, str], cover_file: Path | None, *, replace_cover: bool = False) -> bool:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_WRITE_EXTENSIONS:
        raise ValueError(f"unsupported write format: {suffix or '<none>'}")
    if suffix == ".flac":
        return _write_flac(path, tags, cover_file, replace_cover)
    return _write_easy(path, tags)


def apply_album_plan(
    plan: AlbumPlan,
    *,
    allow_protected: bool = False,
    replace_cover: bool = False,
) -> list[ApplyResult]:
    assert_write_allowed(plan.path, allow_protected=allow_protected)

    results: list[ApplyResult] = []
    for track in plan.tracks:
        warnings: list[str] = []
        try:
            changed = write_track(
                track.path,
                track.tags,
                plan.cover_file,
                replace_cover=replace_cover,
            )
            results.append(ApplyResult(path=track.path, changed=changed, warnings=warnings))
        except Exception as exc:
            warnings.append(str(exc))
            results.append(ApplyResult(path=track.path, changed=False, skipped=True, warnings=warnings))
    return results

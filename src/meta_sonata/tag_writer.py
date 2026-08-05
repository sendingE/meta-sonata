from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    ID3NoHeaderError,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TXXX,
    USLT,
)
from mutagen.mp4 import MP4, MP4Cover

from .models import AlbumPlan, ApplyResult
from .safety import assert_write_allowed


SUPPORTED_WRITE_EXTENSIONS = {".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus"}
EDITABLE_TRACK_FIELDS = {
    "title",
    "artist",
    "album",
    "albumartist",
    "date",
    "genre",
    "tracknumber",
    "discnumber",
}

CUSTOM_TAG_DESCRIPTIONS = {
    "catalognumber": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "musicinfo_source": "MUSICINFO_SOURCE",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_recordingid": "MusicBrainz Recording Id",
    "musicbrainz_trackid": "MusicBrainz Track Id",
    "lyrics_source": "LYRICS_SOURCE",
    "lyrics_score": "LYRICS_SCORE",
}


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


def _frame_text(frame) -> str:
    values = getattr(frame, "text", None)
    if isinstance(values, list):
        return str(values[0]) if values else ""
    return str(values or "")


def _write_mp3(path: Path, tags: dict[str, str], cover_file: Path | None, replace_cover: bool) -> bool:
    try:
        audio = ID3(str(path))
    except ID3NoHeaderError:
        audio = ID3()
    changed = False
    frames = {
        "title": ("TIT2", TIT2),
        "artist": ("TPE1", TPE1),
        "albumartist": ("TPE2", TPE2),
        "album": ("TALB", TALB),
        "date": ("TDRC", TDRC),
        "genre": ("TCON", TCON),
        "tracknumber": ("TRCK", TRCK),
        "discnumber": ("TPOS", TPOS),
        "label": ("TPUB", TPUB),
    }
    for key, (frame_id, frame_type) in frames.items():
        value = tags.get(key)
        if not value:
            continue
        current = audio.getall(frame_id)
        if not current or _frame_text(current[0]) != value:
            audio.setall(frame_id, [frame_type(encoding=3, text=[value])])
            changed = True

    for key, desc in CUSTOM_TAG_DESCRIPTIONS.items():
        value = tags.get(key)
        if not value:
            continue
        frame_id = f"TXXX:{desc}"
        current = audio.get(frame_id)
        if current is None or _frame_text(current) != value:
            audio.setall(frame_id, [TXXX(encoding=3, desc=desc, text=[value])])
            changed = True

    lyrics = tags.get("syncedlyrics") or tags.get("lyrics") or tags.get("unsyncedlyrics")
    if lyrics:
        current = next(iter(audio.getall("USLT")), None)
        if current is None or str(current.text) != lyrics:
            audio.setall("USLT", [USLT(encoding=3, lang="eng", desc="", text=lyrics)])
            changed = True
        if tags.get("syncedlyrics"):
            current_synced = audio.get("TXXX:SYNCEDLYRICS")
            if current_synced is None or _frame_text(current_synced) != tags["syncedlyrics"]:
                audio.setall(
                    "TXXX:SYNCEDLYRICS",
                    [TXXX(encoding=3, desc="SYNCEDLYRICS", text=[tags["syncedlyrics"]])],
                )
                changed = True

    if cover_file:
        current = audio.getall("APIC")
        if replace_cover or not current:
            if replace_cover:
                audio.delall("APIC")
            audio.add(
                APIC(
                    encoding=3,
                    mime=_mime_for_cover(cover_file),
                    type=3,
                    desc="Cover",
                    data=cover_file.read_bytes(),
                )
            )
            changed = True
    if changed:
        audio.save(str(path), v2_version=3)
    return changed


def _pair(value: str) -> tuple[int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", value)[:2]]
    if not numbers:
        return (0, 0)
    return (numbers[0], numbers[1] if len(numbers) > 1 else 0)


def _write_mp4(path: Path, tags: dict[str, str], cover_file: Path | None, replace_cover: bool) -> bool:
    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    mp4_tags = audio.tags
    assert mp4_tags is not None
    changed = False
    mapping = {
        "title": "\xa9nam",
        "artist": "\xa9ART",
        "albumartist": "aART",
        "album": "\xa9alb",
        "date": "\xa9day",
        "genre": "\xa9gen",
        "label": "\xa9pub",
    }
    for key, atom in mapping.items():
        value = tags.get(key)
        if value and mp4_tags.get(atom) != [value]:
            mp4_tags[atom] = [value]
            changed = True
    for key, atom in (("tracknumber", "trkn"), ("discnumber", "disk")):
        value = tags.get(key)
        rendered = [_pair(value)] if value else None
        if rendered and mp4_tags.get(atom) != rendered:
            mp4_tags[atom] = rendered
            changed = True

    lyrics = tags.get("syncedlyrics") or tags.get("lyrics") or tags.get("unsyncedlyrics")
    if lyrics and mp4_tags.get("\xa9lyr") != [lyrics]:
        mp4_tags["\xa9lyr"] = [lyrics]
        changed = True
    for key, desc in CUSTOM_TAG_DESCRIPTIONS.items():
        value = tags.get(key)
        atom = f"----:com.apple.iTunes:{desc}"
        rendered = [value.encode("utf-8")] if value else None
        if rendered and mp4_tags.get(atom) != rendered:
            mp4_tags[atom] = rendered
            changed = True
    if cover_file:
        current = mp4_tags.get("covr") or []
        if replace_cover or not current:
            image_format = (
                MP4Cover.FORMAT_PNG
                if _mime_for_cover(cover_file) == "image/png"
                else MP4Cover.FORMAT_JPEG
            )
            mp4_tags["covr"] = [MP4Cover(cover_file.read_bytes(), imageformat=image_format)]
            changed = True
    if changed:
        audio.save()
    return changed


def _write_ogg(path: Path, tags: dict[str, str], cover_file: Path | None, replace_cover: bool) -> bool:
    audio = MutagenFile(str(path), easy=False)
    if audio is None:
        raise ValueError("mutagen could not open file")
    if audio.tags is None:
        audio.add_tags()
    changed = False
    for key, value in tags.items():
        current = audio.tags.get(key, [""])[0]
        if current != value:
            audio.tags[key] = [value]
            changed = True
    if cover_file:
        current = audio.tags.get("metadata_block_picture") or []
        if replace_cover or not current:
            picture = Picture()
            picture.type = 3
            picture.mime = _mime_for_cover(cover_file)
            picture.desc = "Cover"
            picture.data = cover_file.read_bytes()
            audio.tags["metadata_block_picture"] = [
                base64.b64encode(picture.write()).decode("ascii")
            ]
            changed = True
    if changed:
        audio.save()
    return changed


def write_track(path: Path, tags: dict[str, str], cover_file: Path | None, *, replace_cover: bool = False) -> bool:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_WRITE_EXTENSIONS:
        raise ValueError(f"unsupported write format: {suffix or '<none>'}")
    if suffix == ".flac":
        return _write_flac(path, tags, cover_file, replace_cover)
    if suffix == ".mp3":
        return _write_mp3(path, tags, cover_file, replace_cover)
    if suffix in {".m4a", ".mp4"}:
        return _write_mp4(path, tags, cover_file, replace_cover)
    if suffix in {".ogg", ".opus"}:
        return _write_ogg(path, tags, cover_file, replace_cover)
    return _write_easy(path, tags)


def set_track_field(path: Path, key: str, value: str | None) -> bool:
    if key not in EDITABLE_TRACK_FIELDS:
        raise ValueError(f"unsupported editable field: {key}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_WRITE_EXTENSIONS:
        raise ValueError(f"unsupported write format: {suffix or '<none>'}")

    if suffix == ".flac":
        audio = FLAC(str(path))
        current = audio.get(key, [None])[0]
        if current == value:
            return False
        if value:
            audio[key] = [value]
        elif key in audio:
            del audio[key]
        else:
            return False
        audio.save()
        return True

    if suffix == ".mp3":
        try:
            audio = ID3(str(path))
        except ID3NoHeaderError:
            audio = ID3()
        frames = {
            "title": ("TIT2", TIT2),
            "artist": ("TPE1", TPE1),
            "albumartist": ("TPE2", TPE2),
            "album": ("TALB", TALB),
            "date": ("TDRC", TDRC),
            "genre": ("TCON", TCON),
            "tracknumber": ("TRCK", TRCK),
            "discnumber": ("TPOS", TPOS),
        }
        frame_id, frame_type = frames[key]
        current = audio.getall(frame_id)
        current_value = _frame_text(current[0]) if current else None
        if current_value == value:
            return False
        if value:
            audio.setall(frame_id, [frame_type(encoding=3, text=[value])])
        else:
            audio.delall(frame_id)
        audio.save(str(path), v2_version=3)
        return True

    if suffix in {".m4a", ".mp4"}:
        audio = MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        mp4_tags = audio.tags
        assert mp4_tags is not None
        atoms = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "albumartist": "aART",
            "album": "\xa9alb",
            "date": "\xa9day",
            "genre": "\xa9gen",
            "tracknumber": "trkn",
            "discnumber": "disk",
        }
        atom = atoms[key]
        rendered = [_pair(value)] if value and key in {"tracknumber", "discnumber"} else ([value] if value else None)
        if rendered is not None and mp4_tags.get(atom) == rendered:
            return False
        if rendered is None and atom not in mp4_tags:
            return False
        if rendered is None:
            del mp4_tags[atom]
        else:
            mp4_tags[atom] = rendered
        audio.save()
        return True

    audio = MutagenFile(str(path), easy=False)
    if audio is None:
        raise ValueError("mutagen could not open file")
    if audio.tags is None:
        audio.add_tags()
    current = audio.tags.get(key, [None])[0]
    if current == value:
        return False
    if value:
        audio.tags[key] = [value]
    elif key in audio.tags:
        del audio.tags[key]
    else:
        return False
    audio.save()
    return True


def set_track_lyrics(path: Path, values: dict[str, str]) -> bool:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_WRITE_EXTENSIONS:
        raise ValueError(f"unsupported write format: {suffix or '<none>'}")

    synced = values.get("syncedlyrics")
    generic = values.get("lyrics")
    plain = values.get("unsyncedlyrics")

    if suffix == ".mp3":
        try:
            audio = ID3(str(path))
        except ID3NoHeaderError:
            audio = ID3()
        current_unsynced = next(iter(audio.getall("USLT")), None)
        current_synced = audio.get("TXXX:SYNCEDLYRICS")
        current = {
            "lyrics": str(current_unsynced.text) if current_unsynced else None,
            "syncedlyrics": _frame_text(current_synced) if current_synced else None,
        }
        desired_lyrics = synced or generic or plain
        if current["lyrics"] == desired_lyrics and current["syncedlyrics"] == synced:
            return False
        audio.delall("USLT")
        audio.delall("TXXX:SYNCEDLYRICS")
        if desired_lyrics:
            audio.add(USLT(encoding=3, lang="eng", desc="", text=desired_lyrics))
        if synced:
            audio.add(TXXX(encoding=3, desc="SYNCEDLYRICS", text=[synced]))
        audio.save(str(path), v2_version=3)
        return True

    if suffix in {".m4a", ".mp4"}:
        audio = MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        mp4_tags = audio.tags
        assert mp4_tags is not None
        desired = synced or generic or plain
        rendered = [desired] if desired else None
        if rendered is not None and mp4_tags.get("\xa9lyr") == rendered:
            return False
        if rendered is None and "\xa9lyr" not in mp4_tags:
            return False
        if rendered is None:
            del mp4_tags["\xa9lyr"]
        else:
            mp4_tags["\xa9lyr"] = rendered
        audio.save()
        return True

    audio = FLAC(str(path)) if suffix == ".flac" else MutagenFile(str(path), easy=False)
    if audio is None:
        raise ValueError("mutagen could not open file")
    if audio.tags is None:
        audio.add_tags()
    current = {
        key: str(audio.tags.get(key, [""])[0])
        for key in ("lyrics", "unsyncedlyrics", "syncedlyrics")
        if audio.tags.get(key)
    }
    desired = {key: value for key, value in values.items() if value}
    if current == desired:
        return False
    for key in ("lyrics", "unsyncedlyrics", "syncedlyrics"):
        if key in audio.tags:
            del audio.tags[key]
    for key, value in desired.items():
        audio.tags[key] = [value]
    audio.save()
    return True


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

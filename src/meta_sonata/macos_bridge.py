from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from .catalog import try_default_catalog
from .cover import download_cover
from .lyrics import DEFAULT_LYRICS_SOURCES, embedded_lyrics, enrich_album_plan_with_lyrics
from .models import AUDIO_EXTENSIONS, AlbumMetadata, AlbumPlan, TrackPlan
from .tag_writer import (
    SUPPORTED_WRITE_EXTENSIONS,
    apply_album_plan,
    set_track_field,
    set_track_lyrics,
)
from .track_enrichment import completed_track_tags, resolve_track
from .web import (
    audio_info,
    cover_bytes,
    file_info,
    first_tag,
    lyrics_info,
    normalize_tags,
    run_server_in_thread,
)


class BridgeError(Exception):
    def __init__(self, code: str, *, arguments: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.arguments = arguments or {}


def _validate_audio(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.exists():
        raise BridgeError("file_not_found")
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise BridgeError("unsupported_file")
    return path


def inspect_audio(path: Path, *, artwork_dir: Path | None = None) -> dict[str, Any]:
    path = _validate_audio(path)
    audio = MutagenFile(str(path), easy=True)
    tags = normalize_tags(getattr(audio, "tags", None))
    artwork, artwork_mime = cover_bytes(path)
    artwork_path = None
    if artwork and artwork_dir:
        artwork_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".png" if artwork_mime == "image/png" else ".jpg"
        target = artwork_dir / f"artwork{suffix}"
        target.write_bytes(artwork)
        artwork_path = str(target)
    title = first_tag(tags, "title") or path.stem
    artist = first_tag(tags, "artist")
    album = first_tag(tags, "album")
    embedded = embedded_lyrics(path)
    lyric_tags = {key: [value] for key, value in embedded.items()}
    lyric_detail = lyrics_info(lyric_tags)
    lyric_detail["text"] = (
        embedded.get("syncedlyrics")
        or embedded.get("lyrics")
        or embedded.get("unsyncedlyrics")
        or ""
    )
    summary = {
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": first_tag(tags, "albumartist"),
        "date": first_tag(tags, "date"),
        "genre": first_tag(tags, "genre"),
        "track_number": first_tag(tags, "tracknumber"),
        "disc_number": first_tag(tags, "discnumber"),
        "source": first_tag(tags, "musicinfo_source"),
    }
    return {
        "path": str(path),
        "file": file_info(path),
        "format": audio.__class__.__name__ if audio else None,
        "audio": audio_info(audio),
        "metadata": summary,
        "tags": tags,
        "lyrics": lyric_detail,
        "has_artwork": bool(artwork),
        "artwork_path": artwork_path,
        "writable": path.suffix.lower() in SUPPORTED_WRITE_EXTENSIONS,
    }


FIELD_TO_TAG = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "album_artist": "albumartist",
    "date": "date",
    "genre": "genre",
    "track_number": "tracknumber",
    "disc_number": "discnumber",
}
REVERTIBLE_FIELDS = {*FIELD_TO_TAG, "lyrics"}


def revert_audio_field(
    output: Path,
    original: Path,
    field: str,
    *,
    artwork_dir: Path | None = None,
) -> dict[str, Any]:
    output = _validate_audio(output)
    original = _validate_audio(original)
    if field not in REVERTIBLE_FIELDS:
        raise BridgeError("unsupported_revert_field")
    if field == "lyrics":
        changed = set_track_lyrics(output, embedded_lyrics(original))
    else:
        tag_key = FIELD_TO_TAG[field]
        original_audio = MutagenFile(str(original), easy=True)
        original_value = None
        if original_audio is not None:
            values = original_audio.get(tag_key)
            if values and str(values[0]).strip():
                original_value = str(values[0]).strip()
        changed = set_track_field(output, tag_key, original_value)
    return {
        "output": inspect_audio(output, artwork_dir=artwork_dir),
        "reverted_field": field,
        "changed": changed,
    }


def _unique_copy(source: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / source.name
    if target.exists():
        target = output_dir / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
    shutil.copy2(source, target)
    return target


def enrich_audio_copy(
    source: Path,
    output_dir: Path,
    *,
    lyrics_sources: str = DEFAULT_LYRICS_SOURCES,
) -> dict[str, Any]:
    source = _validate_audio(source)
    if source.suffix.lower() not in SUPPORTED_WRITE_EXTENSIONS:
        raise BridgeError(
            "unsupported_write_format",
            arguments={"format": source.suffix.removeprefix(".").upper() or "UNKNOWN"},
        )
    output_dir = output_dir.expanduser().resolve()
    output = _unique_copy(source, output_dir)
    resolution = resolve_track(output)
    tags = completed_track_tags(output, resolution)
    candidate = resolution.candidate
    metadata = AlbumMetadata(
        artist=tags.get("albumartist") or tags.get("artist"),
        album=tags.get("album"),
        year=(tags.get("date") or "")[:4] or None,
        release_date=tags.get("date"),
        source=(candidate.provider if candidate else "local"),
        source_id=(candidate.source_id if candidate else None),
        source_url=(candidate.source_url if candidate else None),
        confidence=(candidate.score if candidate else 0.0),
    )
    plan = AlbumPlan(
        path=output_dir,
        metadata=metadata,
        tracks=[TrackPlan(path=output, tags=tags)],
        remote_cover_url=candidate.cover_url if candidate else None,
        kind="loose",
        warnings=list(resolution.warnings),
    )
    plan, lyric_report = enrich_album_plan_with_lyrics(
        plan,
        provider_name=lyrics_sources,
        request_delay=0,
    )
    cover_file = None
    cover_warning = None
    if plan.remote_cover_url:
        try:
            cover_file = download_cover(plan.remote_cover_url, output_dir / ".artwork")
        except Exception as exc:
            cover_warning = f"cover_error:{exc}"
    if cover_file:
        plan = replace(plan, cover_file=cover_file)
    apply_results = apply_album_plan(plan, replace_cover=False)
    if not apply_results or apply_results[0].skipped:
        raise BridgeError("write_failed")
    warnings = [*resolution.warnings, *plan.tracks[0].warnings]
    if cover_warning:
        warnings.append(cover_warning)
    result = inspect_audio(output, artwork_dir=output_dir / ".preview")
    return {
        "input_path": str(source),
        "output": result,
        "match": candidate.to_dict() if candidate else None,
        "lyrics_report": lyric_report.to_dict(),
        "changed": apply_results[0].changed,
        "warnings": sorted(set(warnings)),
    }


def serve_library_for_app(root: Path) -> int:
    """Serve the read-only library UI until the native app closes stdin."""
    server, url = run_server_in_thread(
        root,
        host="127.0.0.1",
        port=0,
        catalog=try_default_catalog(),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "url": url,
                "root": str(root.expanduser().resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        sys.stdin.buffer.read()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meta-sonata-mac-backend")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("path")
    inspect.add_argument("--artwork-dir")
    enrich = sub.add_parser("enrich")
    enrich.add_argument("path")
    enrich.add_argument("--output-dir", required=True)
    enrich.add_argument("--lyrics-sources", default=DEFAULT_LYRICS_SOURCES)
    revert = sub.add_parser("revert-field")
    revert.add_argument("output")
    revert.add_argument("--original", required=True)
    revert.add_argument("--field", required=True, choices=sorted(REVERTIBLE_FIELDS))
    revert.add_argument("--artwork-dir")
    library = sub.add_parser("library-server")
    library.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "library-server":
            return serve_library_for_app(Path(args.path))
        if args.command == "inspect":
            payload = inspect_audio(
                Path(args.path),
                artwork_dir=Path(args.artwork_dir) if args.artwork_dir else None,
            )
        elif args.command == "enrich":
            payload = enrich_audio_copy(Path(args.path), Path(args.output_dir))
        else:
            payload = revert_audio_field(
                Path(args.output),
                Path(args.original),
                args.field,
                artwork_dir=Path(args.artwork_dir) if args.artwork_dir else None,
            )
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
        return 0
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, BridgeError)
            else ("library_start_failed" if args.command == "library-server" else "processing_failed")
        )
        arguments = exc.arguments if isinstance(exc, BridgeError) else {}
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_code": code,
                    "error_arguments": arguments,
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

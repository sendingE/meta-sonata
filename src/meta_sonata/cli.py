from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from . import __version__
from .cover import download_cover
from .grouping import group_scans
from .lyrics import (
    DEFAULT_LYRICS_MODE,
    DEFAULT_LYRICS_SOURCES,
    IMPLEMENTED_LYRICS_SOURCES,
    LYRICS_MODE_CHOICES,
    LyricsEnrichmentReport,
    enrich_album_plan_with_lyrics,
)
from .planner import build_plans
from .providers import all_provider_info
from .resolver import resolve_scan
from .safety import (
    PROTECTED_PATHS_ENV,
    ProtectedPathError,
    assert_write_allowed,
    is_protected_path,
    protected_library_paths,
)
from .scanner import DEFAULT_SCAN_DEPTH, scan_root
from .state import (
    PIPELINE_MARKER_NAME,
    STATE_DIR_ENV,
    album_signature,
    default_state_dir,
    has_current_state,
    has_pipeline_marker_since,
    write_state,
)
from .tag_writer import apply_album_plan
from .web import serve_web


def _json_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _load_scans(path: str, max_depth: int | None = DEFAULT_SCAN_DEPTH) -> list:
    return group_scans(scan_root(Path(path), max_depth=max_depth))


def _source_names(args: argparse.Namespace) -> list[str] | None:
    sources = getattr(args, "sources", None)
    if not sources:
        return None
    return [part.strip() for part in sources.split(",") if part.strip()]


def _state_dir(args: argparse.Namespace) -> Path:
    configured = getattr(args, "state_dir", None)
    if configured:
        return Path(configured).expanduser()
    return default_state_dir()


def _filtered_scans(args: argparse.Namespace) -> list:
    scans = _load_scans(args.path, getattr(args, "max_depth", DEFAULT_SCAN_DEPTH))
    since = getattr(args, "pipeline_marker_since", None)
    if since is not None:
        scans = [
            scan
            for scan in scans
            if has_pipeline_marker_since(
                scan.path,
                since,
                marker_name=getattr(args, "pipeline_marker_name", PIPELINE_MARKER_NAME),
            )
        ]

    if getattr(args, "changed_only", False):
        state_dir = _state_dir(args)
        signatures: dict[Path, str] = {}
        changed_scans = []
        for scan in scans:
            if scan.path not in signatures:
                signatures[scan.path] = album_signature(scan.path)
            if not has_current_state(scan.path, signatures[scan.path], state_dir):
                changed_scans.append(scan)
        scans = changed_scans
    return scans


def cmd_doctor(_: argparse.Namespace) -> int:
    print(f"meta-sonata {__version__}")
    print(f"state dir: {default_state_dir()} (override with {STATE_DIR_ENV})")
    print("protected library roots:")
    roots = protected_library_paths()
    if not roots:
        print(f"  none configured; set {PROTECTED_PATHS_ENV} to protect real libraries")
    for root in roots:
        marker = "exists" if root.exists() else "not-mounted-or-not-found"
        print(f"  - {root} [{marker}]")
    try:
        import mutagen  # noqa: F401

        print("mutagen: ok")
    except Exception as exc:
        print(f"mutagen: missing ({exc})")
        return 1
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    rows = all_provider_info()
    for row in rows:
        row["lyrics_implemented"] = row["name"] in IMPLEMENTED_LYRICS_SOURCES
    if args.json:
        print(_json_dump(rows))
        return 0
    for row in rows:
        metadata = "implemented" if row["implemented"] else "planned"
        lyrics = "implemented" if row["lyrics_implemented"] else "-"
        print(
            f"{row['name']:<12} metadata={metadata:<11} "
            f"lyrics={lyrics:<11} {row['display_name']} - {row['note']}"
        )
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    scans = _load_scans(args.path, args.max_depth)
    payload = [scan.to_dict() for scan in scans]
    if args.json:
        print(_json_dump(payload))
        return 0
    for scan in scans:
        protected = " protected" if is_protected_path(scan.path) else ""
        cover = f", cover={scan.cover_file.name}" if scan.cover_file else ", no cover"
        group = f", group={scan.group_key}" if scan.group_key else ""
        print(f"{scan.path}: {scan.kind}, {len(scan.audio_files)} audio{group}{cover}{protected}")
    return 0


def _plans_for_scans(scans: list):
    return build_plans(scans)


def _resolve_for_scans(args: argparse.Namespace, scans: list, *, show_progress: bool = False):
    results = []
    for index, scan in enumerate(scans, start=1):
        if show_progress:
            action = "resolve" if scan.kind == "album" else "loose"
            print(f"{action}: {index}/{len(scans)} {scan.path}", flush=True)
        results.append(
            resolve_scan(
                scan,
                source_names=_source_names(args),
                limit_per_source=args.limit_per_source,
                min_score=args.min_score,
            )
        )
    return results


def cmd_resolve(args: argparse.Namespace) -> int:
    scans = _filtered_scans(args)
    results = _resolve_for_scans(args, scans)
    payload = {
        "version": __version__,
        "root": str(Path(args.path).expanduser()),
        "album_count": len(results),
        "unit_count": len(results),
        "album_group_count": sum(result.scan.kind == "album" for result in results),
        "loose_track_count": sum(
            len(result.scan.audio_files) for result in results if result.scan.kind == "loose"
        ),
        "results": [result.to_dict() for result in results],
    }
    if args.json:
        print(_json_dump(payload))
        return 0
    for result in results:
        identity = result.scan.group_key or "loose tracks"
        print(f"{result.scan.kind}: {identity} @ {result.scan.path}:")
        if result.warnings:
            for warning in result.warnings:
                print(f"  warning: {warning}")
        if not result.candidates:
            print("  no candidates")
            continue
        for candidate in result.candidates[: args.show]:
            print(
                "  "
                f"{candidate.score:.2f} "
                f"{candidate.provider:<11} "
                f"{candidate.artist or '?'} - {candidate.album or '?'}"
                f" ({candidate.year or '?'})"
            )
        best = result.candidates[0]
        accepted = "accepted" if best.score >= args.min_score else "below-threshold"
        print(f"  best: {best.provider}:{best.source_id} {accepted}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    scans = _filtered_scans(args)
    resolutions = _resolve_for_scans(args, scans) if args.scrape else []
    plans = [result.plan for result in resolutions] if args.scrape else _plans_for_scans(scans)
    payload = {
        "version": __version__,
        "root": str(Path(args.path).expanduser()),
        "album_count": len(plans),
        "unit_count": len(plans),
        "album_group_count": sum(plan.kind == "album" for plan in plans),
        "loose_track_count": sum(len(plan.tracks) for plan in plans if plan.kind == "loose"),
        "plans": [plan.to_dict() for plan in plans],
    }
    if args.scrape:
        payload["resolutions"] = [result.to_dict() for result in resolutions]
    rendered = _json_dump(payload)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote audit plan: {args.out}")
    else:
        print(rendered)
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    if args.write:
        try:
            assert_write_allowed(args.path, allow_protected=args.allow_protected)
        except ProtectedPathError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    scans = _filtered_scans(args)
    depth = "unlimited" if args.max_depth is None else str(args.max_depth)
    album_groups = sum(scan.kind == "album" for scan in scans)
    loose_tracks = sum(len(scan.audio_files) for scan in scans if scan.kind == "loose")
    print(
        f"scan: root={Path(args.path).expanduser()} "
        f"files={sum(len(scan.audio_files) for scan in scans)} "
        f"album_groups={album_groups} "
        f"loose_tracks={loose_tracks} "
        f"max_depth={depth}"
    )
    resolutions = _resolve_for_scans(args, scans, show_progress=True) if args.scrape else []
    plans = [result.plan for result in resolutions] if args.scrape else _plans_for_scans(scans)
    lyric_reports: list[LyricsEnrichmentReport] = []
    if args.lyrics:
        enriched = []
        for index, plan in enumerate(plans, start=1):
            print(f"lyrics: {index}/{len(plans)} {plan.path}", flush=True)
            try:
                plan, report = enrich_album_plan_with_lyrics(
                    plan,
                    provider_name=args.lyrics_source,
                    mode=args.lyrics_mode,
                    overwrite=args.lyrics_overwrite,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            enriched.append(plan)
            lyric_reports.append(report)
        plans = enriched

    if not args.write:
        print(f"dry run: {len(plans)} plan(s)")
        for index, plan in enumerate(plans):
            md = plan.metadata
            bits = [
                f"artist={md.artist or '?'}",
                f"album={md.album or '?'}",
                f"year={md.year or '?'}",
                f"tracks={len(plan.tracks)}",
                f"confidence={md.confidence:.2f}",
            ]
            if md.label:
                bits.append(f"label={md.label}")
            if md.catalog_number:
                bits.append(f"catalog={md.catalog_number}")
            if md.barcode:
                bits.append(f"barcode={md.barcode}")
            if md.source_id:
                bits.append(f"source_id={md.source_id}")
            if plan.protected:
                bits.append("PROTECTED")
            if plan.remote_cover_url:
                bits.append("remote_cover=yes")
            if lyric_reports:
                report = lyric_reports[index]
                lyric_bits = [f"{report.found}/{report.total}"]
                if report.skipped_existing:
                    lyric_bits.append(f"skipped_existing={report.skipped_existing}")
                if report.migrated_existing:
                    lyric_bits.append(f"migrated_existing={report.migrated_existing}")
                if report.missing:
                    lyric_bits.append(f"missing={report.missing}")
                if report.errors:
                    lyric_bits.append(f"errors={report.errors}")
                bits.append("lyrics=" + ",".join(lyric_bits))
            if plan.warnings:
                bits.append("warnings=" + ",".join(plan.warnings))
            identity = plan.group_key or "loose tracks"
            print(f"- {plan.kind}: {identity} @ {plan.path}: " + "  ".join(bits))
        print("nothing written; pass --write to apply")
        return 0

    changed = skipped = 0
    state_runs: dict[Path, dict] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="meta-sonata-cover-") as tmp:
            cover_tmp = Path(tmp)
            for plan in plans:
                if plan.path not in state_runs:
                    state_runs[plan.path] = {
                        "before_signature": album_signature(plan.path),
                        "changed": 0,
                        "track_count": 0,
                        "skipped": False,
                        "units": [],
                        "warnings": [],
                    }
                state_run = state_runs[plan.path]
                plan_to_write = plan
                if plan.remote_cover_url and not plan.cover_file:
                    try:
                        cover_file = download_cover(plan.remote_cover_url, cover_tmp / plan.path.name)
                        plan_to_write = replace(plan, cover_file=cover_file)
                    except Exception as exc:
                        print(f"cover skip {plan.path}: {exc}", file=sys.stderr)
                results = apply_album_plan(
                    plan_to_write,
                    allow_protected=args.allow_protected,
                    replace_cover=args.replace_cover,
                )
                for result in results:
                    changed += int(result.changed)
                    skipped += int(result.skipped)
                    if result.skipped:
                        print(f"skip {result.path}: {'; '.join(result.warnings)}")
                state_run["changed"] += sum(1 for result in results if result.changed)
                state_run["track_count"] += len(results)
                state_run["skipped"] = state_run["skipped"] or any(result.skipped for result in results)
                state_run["units"].append(
                    {
                        "kind": plan.kind,
                        "group_key": plan.group_key,
                        "metadata": plan.metadata.to_dict(),
                    }
                )
                state_run["warnings"].extend(plan.warnings)

            if not args.no_state:
                for path, state_run in state_runs.items():
                    if state_run["skipped"]:
                        continue
                    write_state(
                        path,
                        {
                            "album_signature": album_signature(path),
                            "before_signature": state_run["before_signature"],
                            "changed": state_run["changed"],
                            "track_count": state_run["track_count"],
                            "scrape": bool(args.scrape),
                            "sources": _source_names(args) or [],
                            "units": state_run["units"],
                            "warnings": state_run["warnings"],
                        },
                        _state_dir(args),
                    )
    except ProtectedPathError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if lyric_reports:
        total_report = LyricsEnrichmentReport()
        for report in lyric_reports:
            total_report = total_report.merge(report)
        print(
            "lyrics: "
            f"found={total_report.found} "
            f"missing={total_report.missing} "
            f"skipped_existing={total_report.skipped_existing} "
            f"migrated_existing={total_report.migrated_existing} "
            f"instrumental={total_report.instrumental} "
            f"errors={total_report.errors}"
        )
    print(f"write complete: changed={changed} skipped={skipped}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    serve_web(Path(args.path), host=args.host, port=args.port)
    return 0


def add_incremental_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Skip albums whose external meta-sonata state matches current content",
    )
    parser.add_argument(
        "--state-dir",
        help=f"Directory for meta-sonata state files (default: {STATE_DIR_ENV} or platform user state dir)",
    )
    parser.add_argument(
        "--pipeline-marker-since",
        type=float,
        help="Only include albums whose pipeline marker mtime is at or after this Unix epoch",
    )
    parser.add_argument(
        "--pipeline-marker-name",
        default=PIPELINE_MARKER_NAME,
        help=f"Pipeline marker filename to inspect (default: {PIPELINE_MARKER_NAME})",
    )


def non_negative_depth(value: str) -> int:
    depth = int(value)
    if depth < 0:
        raise argparse.ArgumentTypeError("depth must be zero or greater")
    return depth


def add_scan_depth_args(parser: argparse.ArgumentParser) -> None:
    depth = parser.add_mutually_exclusive_group()
    depth.add_argument(
        "--max-depth",
        type=non_negative_depth,
        default=DEFAULT_SCAN_DEPTH,
        help=f"Maximum album discovery depth (default: {DEFAULT_SCAN_DEPTH}; 0 scans only PATH)",
    )
    depth.add_argument(
        "--recursive",
        action="store_const",
        const=None,
        dest="max_depth",
        help="Discover albums recursively without a depth limit",
    )


def add_tagging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "path",
        help="Album directory or music root to search for albums",
    )
    parser.add_argument("--write", action="store_true", help="Actually write tags")
    parser.add_argument("--sources", default="musicbrainz,itunes,netease")
    parser.add_argument("--limit-per-source", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.72)
    add_scan_depth_args(parser)
    add_incremental_args(parser)
    parser.add_argument("--no-state", action="store_true", help="Do not write external meta-sonata state")
    parser.add_argument("--replace-cover", action="store_true", help="Replace existing embedded covers")
    parser.add_argument(
        "--lyrics-source",
        default=DEFAULT_LYRICS_SOURCES,
        help=f"Comma-separated music-tag compatible lyric sources (default: {DEFAULT_LYRICS_SOURCES})",
    )
    parser.add_argument(
        "--lyrics-mode",
        choices=LYRICS_MODE_CHOICES,
        default=DEFAULT_LYRICS_MODE,
        help=f"Which lyrics format to embed (default: {DEFAULT_LYRICS_MODE})",
    )
    parser.add_argument("--lyrics-overwrite", action="store_true", help="Replace existing embedded lyrics")
    parser.add_argument(
        "--allow-protected",
        action="store_true",
        help="Allow writes inside protected library roots; avoid for experiments",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meta-sonata")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show environment and safety settings")
    doctor.set_defaults(func=cmd_doctor)

    sources = sub.add_parser("sources", help="List metadata providers aligned with music-tag")
    sources.add_argument("--json", action="store_true", help="Print JSON")
    sources.set_defaults(func=cmd_sources)

    scan = sub.add_parser("scan", help="Scan and classify music folders without writing tags")
    scan.add_argument("path")
    scan.add_argument("--json", action="store_true", help="Print JSON")
    add_scan_depth_args(scan)
    scan.set_defaults(func=cmd_scan)

    resolve = sub.add_parser("resolve", help="Resolve local album folders against online metadata providers")
    resolve.add_argument("path")
    resolve.add_argument("--sources", default="musicbrainz,itunes,netease")
    resolve.add_argument("--limit-per-source", type=int, default=5)
    resolve.add_argument("--min-score", type=float, default=0.72)
    resolve.add_argument("--show", type=int, default=5)
    resolve.add_argument("--json", action="store_true", help="Print JSON")
    add_scan_depth_args(resolve)
    add_incremental_args(resolve)
    resolve.set_defaults(func=cmd_resolve)

    audit = sub.add_parser("audit", help="Build an auditable metadata plan")
    audit.add_argument("path")
    audit.add_argument("--out", help="Write plan JSON to a file")
    audit.add_argument("--scrape", action="store_true", help="Use online metadata providers to fill missing fields")
    audit.add_argument("--sources", default="musicbrainz,itunes,netease")
    audit.add_argument("--limit-per-source", type=int, default=5)
    audit.add_argument("--min-score", type=float, default=0.72)
    add_scan_depth_args(audit)
    add_incremental_args(audit)
    audit.set_defaults(func=cmd_audit)

    tag = sub.add_parser("tag", help="Apply local metadata tags")
    add_tagging_args(tag)
    tag.add_argument("--scrape", action="store_true", help="Use online metadata providers to fill missing fields")
    tag.add_argument("--lyrics", action="store_true", help="Fetch and embed lyrics after metadata resolution")
    tag.set_defaults(func=cmd_tag)

    enrich = sub.add_parser(
        "enrich",
        help="Fill metadata, cover art, and lyrics using local tags plus online sources",
    )
    add_tagging_args(enrich)
    enrich.add_argument(
        "--no-scrape",
        action="store_false",
        dest="scrape",
        help="Disable online album metadata lookup",
    )
    enrich.add_argument(
        "--no-lyrics",
        action="store_false",
        dest="lyrics",
        help="Disable online lyrics lookup",
    )
    enrich.set_defaults(func=cmd_tag, scrape=True, lyrics=True)

    web = sub.add_parser("web", help="Run the read-only metadata browser")
    web.add_argument("path", help="Library or staging directory to browse")
    web.add_argument("--host", default="127.0.0.1", help="Bind host")
    web.add_argument("--port", type=int, default=8765, help="Bind port")
    web.set_defaults(func=cmd_web)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

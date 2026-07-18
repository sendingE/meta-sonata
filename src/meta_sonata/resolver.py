from __future__ import annotations

from dataclasses import dataclass, replace

from mutagen import File as MutagenFile

from .matching import text_similarity
from .models import AlbumPlan, AlbumScan, ScrapeCandidate
from .planner import build_album_plan, build_loose_plan
from .providers import get_providers, scrape_candidates
from .tag_hints import local_metadata_for_scan


def _track_durations_ms(scan: AlbumScan) -> list[int] | None:
    durations: list[int] = []
    for path in scan.audio_files:
        try:
            audio = MutagenFile(str(path), easy=False)
            length = getattr(getattr(audio, "info", None), "length", None)
            if length is None:
                return None
            durations.append(round(float(length) * 1000))
        except Exception:
            return None
    return durations or None


def conservative_release_candidate(
    candidates: list[ScrapeCandidate],
    *,
    min_score: float,
    tie_margin: float = 0.01,
) -> tuple[ScrapeCandidate | None, str | None]:
    if not candidates:
        return None, None
    best = candidates[0]
    if best.score < min_score:
        return best, None
    peers = []
    for candidate in candidates:
        same_release_family = (
            candidate.provider == best.provider
            and text_similarity(candidate.artist, best.artist) >= 0.95
            and text_similarity(candidate.album, best.album) >= 0.95
            and (not candidate.year or not best.year or candidate.year == best.year)
            and (
                not candidate.tracks
                or not best.tracks
                or len(candidate.tracks) == len(best.tracks)
            )
        )
        close_score = candidate.score >= min_score and best.score - candidate.score <= tie_margin
        if same_release_family or close_score:
            peers.append(candidate)
    identities = {
        (candidate.catalog_number or "", candidate.barcode or "")
        for candidate in peers
        if candidate.catalog_number or candidate.barcode
    }
    if len(identities) <= 1:
        return best, None

    warning = "ambiguous_release_identity"
    tracks = [replace(track, source_id=None) for track in best.tracks]
    return (
        replace(
            best,
            source_id="",
            catalog_number=None,
            barcode=None,
            cover_url=None,
            source_url=None,
            tracks=tracks,
            warnings=[*best.warnings, warning],
        ),
        warning,
    )


@dataclass(frozen=True)
class ResolveResult:
    scan: AlbumScan
    candidates: list[ScrapeCandidate]
    warnings: list[str]
    plan: AlbumPlan

    def to_dict(self) -> dict:
        return {
            "path": str(self.scan.path),
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": self.warnings,
            "plan": self.plan.to_dict(),
        }


def resolve_scan(
    scan: AlbumScan,
    *,
    source_names: list[str] | None = None,
    limit_per_source: int = 5,
    min_score: float = 0.72,
) -> ResolveResult:
    if scan.kind == "loose":
        return ResolveResult(
            scan=scan,
            candidates=[],
            warnings=["loose_tracks_skip_album_scrape"],
            plan=build_loose_plan(scan),
        )
    local = local_metadata_for_scan(scan)
    providers = get_providers(source_names)
    candidates, warnings = scrape_candidates(
        local,
        providers=providers,
        limit_per_source=limit_per_source,
        local_track_count=len(scan.audio_files),
        local_track_durations_ms=_track_durations_ms(scan),
    )
    best, identity_warning = conservative_release_candidate(candidates, min_score=min_score)
    if identity_warning:
        warnings.append(identity_warning)
    plan = build_album_plan(scan, scraped=best, min_scrape_score=min_score)
    return ResolveResult(scan=scan, candidates=candidates, warnings=warnings, plan=plan)

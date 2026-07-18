from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from opencc import OpenCC

from .models import AlbumMetadata, ScrapeCandidate


LIVE_WORDS = {
    "live",
    "concert",
    "tour",
    "演唱会",
    "演唱會",
    "现场",
    "現場",
    "音乐会",
    "音樂會",
}

T2S_CONVERTER = OpenCC("t2s")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = T2S_CONVERTER.convert(value)
    value = re.sub(r"[\[\]{}()（）【】《》〈〉「」『』.,，。:：;；!！?？'\"`~～]", " ", value)
    value = re.sub(r"[_/\\|+&]", " ", value)
    return " ".join(value.split())


def text_similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        shorter = min(len(left_norm), len(right_norm))
        longer = max(len(left_norm), len(right_norm))
        return max(0.72, shorter / longer)
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def has_live_words(value: str | None) -> bool:
    norm = normalize_text(value)
    return any(word in norm for word in LIVE_WORDS)


def duration_mismatch_ms(
    local_track_durations_ms: list[int] | None,
    candidate: ScrapeCandidate,
) -> int | None:
    if not local_track_durations_ms or len(local_track_durations_ms) != len(candidate.tracks):
        return None
    remote = [track.duration_ms for track in candidate.tracks]
    if any(duration is None for duration in remote):
        return None
    return max(
        abs(local - remote_duration)
        for local, remote_duration in zip(local_track_durations_ms, remote)
        if remote_duration is not None
    )


def score_candidate(
    local: AlbumMetadata,
    candidate: ScrapeCandidate,
    *,
    local_track_count: int = 0,
    local_track_durations_ms: list[int] | None = None,
) -> float:
    album_score = max(
        (text_similarity(value, candidate.album) for value in [local.album, *local.album_aliases]),
        default=0.0,
    )
    artist_score = max(
        (text_similarity(value, candidate.artist) for value in [local.artist, *local.artist_aliases]),
        default=0.0,
    )
    score = 0.58 * album_score + 0.27 * artist_score

    if local.year and candidate.year:
        score += 0.08 if local.year == candidate.year else -0.08
    elif candidate.year:
        score += 0.02

    if local_track_count and candidate.tracks:
        diff = abs(local_track_count - len(candidate.tracks))
        if diff == 0:
            score += 0.07
        elif diff <= 2:
            score -= 0.25
        else:
            score -= min(0.35, 0.25 + diff * 0.025)

    max_duration_diff = duration_mismatch_ms(local_track_durations_ms, candidate)
    if max_duration_diff is not None:
        if max_duration_diff <= 1_500:
            score += 0.03
        elif max_duration_diff > 8_000:
            score -= 0.32
        elif max_duration_diff > 5_000:
            score -= 0.18
        elif max_duration_diff > 3_000:
            score -= 0.08

    local_is_live = has_live_words(local.album) or has_live_words(" ".join(local.edition))
    candidate_is_live = has_live_words(candidate.album) or has_live_words(candidate.release_type)
    if candidate_is_live and not local_is_live:
        score -= 0.25

    if album_score < 0.45:
        score -= 0.12
    if local.artist and candidate.artist and artist_score < 0.45:
        score -= 0.08

    return max(0.0, min(1.0, score))


def best_candidate(
    local: AlbumMetadata,
    candidates: list[ScrapeCandidate],
    *,
    local_track_count: int = 0,
    local_track_durations_ms: list[int] | None = None,
) -> ScrapeCandidate | None:
    if not candidates:
        return None
    scored = [
        candidate
        for candidate in (
            ScrapeCandidate(
                **{
                    **c.__dict__,
                    "score": score_candidate(
                        local,
                        c,
                        local_track_count=local_track_count,
                        local_track_durations_ms=local_track_durations_ms,
                    ),
                }
            )
            for c in candidates
        )
    ]
    return max(scored, key=lambda c: c.score)

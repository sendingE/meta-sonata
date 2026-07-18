import unittest
import shutil
import subprocess
import tempfile
from pathlib import Path

from mutagen.flac import FLAC

from meta_sonata.lyrics import (
    LyricsCandidate,
    LyricsResult,
    MusicTagLyricsProvider,
    enrich_album_plan_with_lyrics,
    lyrics_tags,
    music_tag_keyword,
    normalize_synced_lyrics,
    score_lyrics_candidate,
)
from meta_sonata.models import AlbumMetadata, AlbumPlan, TrackPlan


class FakeLyricsProvider:
    name = "fake"

    def get_lyrics(self, **kwargs):
        return LyricsResult(
            provider=self.name,
            source_id="lyric-1",
            plain_lyrics="Plain line",
            synced_lyrics="[00:01.00]Synced line",
        )


class FakeAliasLyricsProvider:
    name = "fake-alias"

    def get_lyrics(self, **kwargs):
        if kwargs["artist_name"] != "约翰·塞巴斯蒂安·巴赫":
            return None
        return LyricsResult(
            provider=self.name,
            source_id="localized-lyric",
            plain_lyrics="Plain line",
            synced_lyrics="[00:01.00]Synced line",
            score=1.0,
        )


class FakeLyricsSource:
    def __init__(self, name, candidate, lyric=None):
        self.name = name
        self.candidate = candidate
        self.lyric = lyric

    def search(self, **kwargs):
        return [self.candidate]

    def fetch_lyric(self, source_id):
        return self.lyric or f"[00:01.00]{source_id}"


class LyricsTest(unittest.TestCase):
    def test_existing_lrc_in_generic_tag_is_migrated_without_fetching(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate a temporary FLAC")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "01. Public Domain Song.flac"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=44100:cl=stereo",
                    "-t",
                    "0.05",
                    "-c:a",
                    "flac",
                    str(path),
                ],
                check=True,
            )
            lrc = "[00:01.0]Public domain test line"
            audio = FLAC(path)
            audio["lyrics"] = lrc
            audio.save()
            plan = AlbumPlan(
                path=Path(tmp),
                metadata=AlbumMetadata(artist="Test Artist", album="Test Album"),
                tracks=[
                    TrackPlan(
                        path=path,
                        tags={"artist": "Test Artist", "album": "Test Album", "title": "Public Domain Song"},
                    )
                ],
            )

            class FailingProvider:
                name = "must-not-run"

                def get_lyrics(self, **kwargs):
                    raise AssertionError("existing LRC migration must not fetch lyrics")

            enriched, report = enrich_album_plan_with_lyrics(
                plan,
                provider=FailingProvider(),
                request_delay=0,
            )

            self.assertEqual(report.migrated_existing, 1)
            self.assertEqual(report.skipped_existing, 0)
            self.assertEqual(enriched.tracks[0].tags["syncedlyrics"], lrc)

    def test_synced_lyrics_are_sorted_without_moving_metadata_lines(self):
        value = "[ar:Scott Joplin]\n[00:02.00]Second\n[00:01.00]First"

        normalized = normalize_synced_lyrics(value)

        self.assertEqual(
            normalized,
            "[ar:Scott Joplin]\n[00:01.00]First\n[00:02.00]Second",
        )

    def test_enrichment_retries_with_structured_album_aliases(self):
        plan = AlbumPlan(
            path=Path("/tmp/album"),
            metadata=AlbumMetadata(
                artist="Johann Sebastian Bach",
                album="Goldberg Variations",
                artist_aliases=["约翰·塞巴斯蒂安·巴赫"],
                album_aliases=["哥德堡变奏曲"],
            ),
            tracks=[
                TrackPlan(
                    path=Path("/tmp/album/01.flac"),
                    tags={
                        "artist": "Johann Sebastian Bach",
                        "album": "Goldberg Variations",
                        "title": "Aria",
                    },
                )
            ],
        )

        enriched, report = enrich_album_plan_with_lyrics(
            plan,
            provider=FakeAliasLyricsProvider(),
            overwrite=True,
            request_delay=0,
        )

        self.assertEqual(report.found, 1)
        self.assertEqual(enriched.tracks[0].tags["lyrics_source"], "fake-alias:localized-lyric")

    def test_provider_selects_best_candidate_across_all_sources(self):
        earlier = FakeLyricsSource(
            "earlier",
            LyricsCandidate(
                source="earlier",
                source_id="weaker-version",
                title="Maple Leaf Rag (New Version)",
                artist="Scott Joplin",
                album="Maple Leaf Rag (New Version)",
            ),
        )
        later = FakeLyricsSource(
            "later",
            LyricsCandidate(
                source="later",
                source_id="exact-version",
                title="Maple Leaf Rag",
                artist="Scott Joplin",
                album="Maple Leaf Rag",
            ),
        )
        provider = MusicTagLyricsProvider(["fake"])
        provider.sources = [earlier, later]

        result = provider.get_lyrics(
            artist_name="Scott Joplin",
            track_name="Maple Leaf Rag",
            album_name="Maple Leaf Rag",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.provider, "later")
        self.assertEqual(result.source_id, "exact-version")

    def test_provider_rejects_lyric_with_conflicting_embedded_title(self):
        source = FakeLyricsSource(
            "bad-payload",
            LyricsCandidate(
                source="bad-payload",
                source_id="wrong-lyric",
                title="Orinoco Flow",
                artist="Enya",
                album="Watermark",
            ),
            lyric="[ti:caribbean blue]\n[00:01.00]So the world goes round",
        )
        provider = MusicTagLyricsProvider(["fake"])
        provider.sources = [source]

        result = provider.get_lyrics(
            artist_name="Enya",
            track_name="Orinoco Flow",
            album_name="Watermark",
        )

        self.assertIsNone(result)

    def test_prefer_synced_writes_synced_when_available(self):
        result = LyricsResult(
            provider="fake",
            source_id="1",
            plain_lyrics="Plain line",
            synced_lyrics="[00:01.00]Synced line",
        )

        tags = lyrics_tags(result, mode="prefer-synced")

        self.assertEqual(tags["lyrics"], "[00:01.00]Synced line")
        self.assertEqual(tags["syncedlyrics"], "[00:01.00]Synced line")
        self.assertEqual(tags["lyrics_source"], "fake:1")

    def test_enrich_album_plan_adds_lyrics_to_tracks(self):
        plan = AlbumPlan(
            path=Path("/tmp/album"),
            metadata=AlbumMetadata(artist="Scott Joplin", album="Maple Leaf Rag"),
            tracks=[
                TrackPlan(
                    path=Path("/tmp/album/01. Maple Leaf Rag.flac"),
                    tags={"artist": "Scott Joplin", "album": "Maple Leaf Rag", "title": "Maple Leaf Rag"},
                )
            ],
        )

        enriched, report = enrich_album_plan_with_lyrics(
            plan,
            provider=FakeLyricsProvider(),
            mode="both",
            overwrite=True,
            request_delay=0,
        )

        tags = enriched.tracks[0].tags
        self.assertEqual(report.found, 1)
        self.assertEqual(tags["lyrics"], "[00:01.00]Synced line")
        self.assertEqual(tags["unsyncedlyrics"], "Plain line")
        self.assertEqual(tags["syncedlyrics"], "[00:01.00]Synced line")

    def test_music_tag_keyword_matches_plugin_behavior(self):
        self.assertEqual(music_tag_keyword("Maple Leaf Rag", "Scott Joplin"), "Maple Leaf Rag-Scott Joplin")
        self.assertEqual(music_tag_keyword("Scott Joplin - Maple Leaf Rag", "Scott Joplin"), "Scott Joplin - Maple Leaf Rag")

    def test_lyrics_scoring_penalizes_live_mismatch(self):
        studio = LyricsCandidate(
            source="fake",
            source_id="studio",
            title="Maple Leaf Rag",
            artist="Scott Joplin",
            album="Maple Leaf Rag",
        )
        live = LyricsCandidate(
            source="fake",
            source_id="live",
            title="Maple Leaf Rag Live",
            artist="Scott Joplin",
            album="Concert",
        )

        studio_score = score_lyrics_candidate(
            track_name="Maple Leaf Rag",
            artist_name="Scott Joplin",
            album_name="Maple Leaf Rag",
            candidate=studio,
        )
        live_score = score_lyrics_candidate(
            track_name="Maple Leaf Rag",
            artist_name="Scott Joplin",
            album_name="Maple Leaf Rag",
            candidate=live,
        )

        self.assertGreater(studio_score, live_score)


if __name__ == "__main__":
    unittest.main()

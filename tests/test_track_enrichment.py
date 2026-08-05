import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta_sonata.track_enrichment import (
    LocalTrackIdentity,
    TrackCandidate,
    TrackResolution,
    completed_track_tags,
    is_promotional_genre,
    local_track_identity,
    resolve_track,
    score_track_candidate,
)


class TrackEnrichmentTest(unittest.TestCase):
    def test_promotional_genre_is_treated_as_dirty_metadata(self):
        self.assertTrue(is_promotional_genre("[60yp.com 分享]"))
        self.assertTrue(is_promotional_genre("[60yp.com分享]"))
        self.assertTrue(is_promotional_genre("www.example.cn 下载"))
        self.assertFalse(is_promotional_genre("Mandopop"))

    def test_completed_tags_replaces_promotional_genre(self):
        resolution = TrackResolution(
            local=LocalTrackIdentity("Song", "Artist", None, None),
            candidate=TrackCandidate(
                provider="test",
                source_id="1",
                title="Song",
                artist="Artist",
                genre="Mandopop",
            ),
            candidates=[],
            warnings=[],
        )
        with patch(
            "meta_sonata.track_enrichment.MutagenFile",
            return_value={"title": ["Song"], "genre": ["[60yp.com 分享]"]},
        ):
            tags = completed_track_tags(Path("Song.mp3"), resolution)

        self.assertEqual(tags["genre"], "Mandopop")

    def test_filename_identity_supports_track_prefix_and_artist(self):
        identity = local_track_identity(Path("01. Björk - Jóga.flac"))

        self.assertEqual(identity.title, "Jóga")
        self.assertEqual(identity.artist, "Björk")

    def test_score_rewards_identity_and_duration_match(self):
        path = Path("Artist - Song.flac")
        identity = local_track_identity(path)
        candidate = TrackCandidate(
            provider="itunes",
            source_id="1",
            title="Song",
            artist="Artist",
            duration_ms=None,
        )

        self.assertGreater(score_track_candidate(identity, candidate), 0.85)

    def test_resolve_track_rejects_ambiguous_close_matches(self):
        def fake_search(identity, limit):
            del identity, limit
            return [
                TrackCandidate("test", "1", "Song", "Artist A"),
                TrackCandidate("test", "2", "Song", "Artist B"),
            ]

        resolution = resolve_track(
            Path("Song.flac"),
            source_names=("test",),
            min_score=0.7,
            searchers={"test": fake_search},
        )

        self.assertIsNone(resolution.candidate)
        self.assertIn("ambiguous_track_identity", resolution.warnings)

    def test_completed_tags_preserve_existing_values_and_fill_missing(self):
        resolution = resolve_track(
            Path("Artist - Song.flac"),
            source_names=("test",),
            searchers={
                "test": lambda identity, limit: [
                    TrackCandidate(
                        provider="test",
                        source_id="remote-1",
                        title="Song",
                        artist="Artist",
                        album="Album",
                        album_artist="Artist",
                        release_date="2024-01-02",
                        genre="Electronic",
                        track_number="3",
                    )
                ]
            },
        )

        tags = completed_track_tags(Path("Artist - Song.flac"), resolution)

        self.assertEqual(tags["title"], "Song")
        self.assertEqual(tags["artist"], "Artist")
        self.assertEqual(tags["album"], "Album")
        self.assertEqual(tags["tracknumber"], "3")
        self.assertEqual(tags["musicinfo_source"], "test:remote-1")

    def test_musicbrainz_recording_id_is_not_mislabeled_as_release_track_id(self):
        candidate = TrackCandidate(
            provider="musicbrainz",
            source_id="recording-mbid",
            title="Song",
            artist="Artist",
            artist_ids=("artist-mbid",),
            recording_id="recording-mbid",
            release_id="release-mbid",
        )
        resolution = TrackResolution(
            local=LocalTrackIdentity("Song", "Artist", None, None),
            candidate=candidate,
            candidates=[candidate],
            warnings=[],
        )

        tags = completed_track_tags(Path("Artist - Song.flac"), resolution)

        self.assertEqual(tags["musicbrainz_recordingid"], "recording-mbid")
        self.assertEqual(tags["musicbrainz_albumid"], "release-mbid")
        self.assertEqual(tags["musicbrainz_artistid"], "artist-mbid")
        self.assertNotIn("musicbrainz_trackid", tags)

    def test_resolve_track_omits_ambiguous_release_fields(self):
        def fake_search(identity, limit):
            del identity, limit
            return [
                TrackCandidate("test", "1", "Song", "Artist", album="Original Album"),
                TrackCandidate("test", "2", "Song", "Artist", album="Greatest Hits"),
            ]

        resolution = resolve_track(
            Path("Artist - Song.flac"),
            source_names=("test",),
            searchers={"test": fake_search},
        )

        self.assertIsNotNone(resolution.candidate)
        self.assertIsNone(resolution.candidate.album)
        self.assertIn("ambiguous_release_identity", resolution.warnings)

    def test_failed_provider_does_not_block_later_provider(self):
        def unavailable(identity, limit):
            del identity, limit
            raise TimeoutError("offline")

        resolution = resolve_track(
            Path("Artist - Song.flac"),
            source_names=("offline", "working"),
            searchers={
                "offline": unavailable,
                "working": lambda identity, limit: [
                    TrackCandidate("working", "1", identity.title, identity.artist)
                ],
            },
        )

        self.assertIsNotNone(resolution.candidate)
        self.assertEqual(resolution.candidate.provider, "working")
        self.assertTrue(any(row.startswith("offline_error:") for row in resolution.warnings))


if __name__ == "__main__":
    unittest.main()

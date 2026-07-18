import unittest

from meta_sonata.album_parser import parse_album_dir
from meta_sonata.matching import score_candidate, text_similarity
from meta_sonata.models import ScrapeCandidate, ScrapedTrack


class MatchingTest(unittest.TestCase):
    def test_folder_aliases_match_localized_candidate(self):
        local = parse_album_dir(
            "Johann Sebastian Bach (巴赫) - Goldberg Variations (哥德堡變奏曲) (1741) [FLAC]"
        )
        localized = ScrapeCandidate(
            provider="fake",
            source_id="localized",
            artist="巴赫",
            album="哥德堡变奏曲",
            year="1741",
        )

        self.assertGreater(score_candidate(local, localized), 0.90)

    def test_traditional_and_simplified_chinese_match(self):
        self.assertEqual(text_similarity("繁體中文", "繁体中文"), 1.0)

    def test_live_candidate_is_penalized_for_studio_album(self):
        local = parse_album_dir("Scott Joplin - Maple Leaf Rag (1899) [FLAC]")
        studio = ScrapeCandidate(
            provider="fake",
            source_id="studio",
            artist="Scott Joplin",
            album="Maple Leaf Rag",
            year="1899",
        )
        live = ScrapeCandidate(
            provider="fake",
            source_id="live",
            artist="Scott Joplin",
            album="Maple Leaf Rag Live Concert",
            year="1899",
            release_type="Live",
        )
        self.assertGreater(score_candidate(local, studio), score_candidate(local, live))
        self.assertLess(score_candidate(local, live), 0.72)

    def test_large_track_duration_mismatch_rejects_exact_release_identity(self):
        local = parse_album_dir("Enya - Watermark (1988) [FLAC]")
        candidate = ScrapeCandidate(
            provider="fake",
            source_id="wrong-edition",
            artist="Enya",
            album="Watermark",
            year="1988",
            tracks=[
                ScrapedTrack(title="Watermark", duration_ms=143_500),
                ScrapedTrack(title="The Longships", duration_ms=218_300),
            ],
        )

        score = score_candidate(
            local,
            candidate,
            local_track_count=2,
            local_track_durations_ms=[143_573, 206_520],
        )

        self.assertLess(score, 0.72)

    def test_close_track_durations_keep_a_strong_match(self):
        local = parse_album_dir("Enya - Watermark (1988) [FLAC]")
        candidate = ScrapeCandidate(
            provider="fake",
            source_id="matching-edition",
            artist="Enya",
            album="Watermark",
            year="1988",
            tracks=[ScrapedTrack(title="Watermark", duration_ms=143_600)],
        )

        score = score_candidate(
            local,
            candidate,
            local_track_count=1,
            local_track_durations_ms=[143_573],
        )

        self.assertGreater(score, 0.95)

    def test_different_track_count_rejects_release_identity(self):
        local = parse_album_dir("Enya - Watermark (1988) [FLAC]")
        candidate = ScrapeCandidate(
            provider="fake",
            source_id="bonus-track-edition",
            artist="Enya",
            album="Watermark",
            year="1988",
            tracks=[ScrapedTrack(title=str(index)) for index in range(12)],
        )

        self.assertLess(score_candidate(local, candidate, local_track_count=11), 0.72)


if __name__ == "__main__":
    unittest.main()

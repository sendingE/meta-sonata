import unittest

from meta_sonata.models import ScrapeCandidate, ScrapedTrack
from meta_sonata.resolver import conservative_release_candidate


class ResolverTest(unittest.TestCase):
    def test_conflicting_same_source_tie_strips_release_identity(self):
        first = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-one",
            artist="Test Artist",
            album="Test Album",
            catalog_number="CAT-1",
            barcode="111",
            cover_url="https://example.test/one.jpg",
            source_url="https://example.test/one",
            tracks=[ScrapedTrack(title="Track", tracknumber="1", discnumber="1", source_id="track-one")],
            score=0.97,
        )
        second = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-two",
            artist="Test Artist",
            album="Test Album",
            catalog_number="CAT-2",
            barcode="222",
            score=0.97,
        )

        candidate, warning = conservative_release_candidate([first, second], min_score=0.72)

        self.assertEqual(warning, "ambiguous_release_identity")
        self.assertEqual(candidate.source_id, "")
        self.assertIsNone(candidate.catalog_number)
        self.assertIsNone(candidate.barcode)
        self.assertIsNone(candidate.cover_url)
        self.assertIsNone(candidate.tracks[0].source_id)
        self.assertEqual(candidate.tracks[0].discnumber, "1")

    def test_clear_winner_keeps_release_identity(self):
        first = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-one",
            artist="Test Artist",
            album="Test Album",
            barcode="111",
            score=0.97,
        )
        second = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-two",
            artist="Test Artist",
            album="Different Album",
            barcode="222",
            score=0.90,
        )

        candidate, warning = conservative_release_candidate([first, second], min_score=0.72)

        self.assertIsNone(warning)
        self.assertEqual(candidate.source_id, "release-one")

    def test_lower_scored_same_album_identity_conflict_is_still_ambiguous(self):
        first = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-one",
            artist="A-Lin",
            album="罪恶感",
            year="2014",
            catalog_number="88875058142",
            barcode="0888750581426",
            tracks=[ScrapedTrack(tracknumber=str(index)) for index in range(1, 11)],
            score=1.0,
        )
        second = ScrapeCandidate(
            provider="musicbrainz",
            source_id="release-two",
            artist="A-Lin",
            album="罪恶感",
            year="2014",
            catalog_number="88875058152",
            barcode="0888750581525",
            tracks=[ScrapedTrack(tracknumber=str(index)) for index in range(1, 11)],
            score=0.68,
        )

        candidate, warning = conservative_release_candidate([first, second], min_score=0.72)

        self.assertEqual(warning, "ambiguous_release_identity")
        self.assertEqual(candidate.source_id, "")
        self.assertIsNone(candidate.catalog_number)
        self.assertIsNone(candidate.barcode)


if __name__ == "__main__":
    unittest.main()

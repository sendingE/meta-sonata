import unittest

from meta_sonata.models import AlbumMetadata, ScrapeCandidate
from meta_sonata.providers import AlbumProvider, scrape_candidates


class AliasOnlyProvider(AlbumProvider):
    name = "alias-only"

    def __init__(self):
        self.calls = []

    def search(self, local, *, limit=5):
        self.calls.append((local.artist, local.album))
        if local.artist == "巴赫" and local.album == "哥德堡變奏曲":
            return [
                ScrapeCandidate(
                    provider=self.name,
                    source_id="localized",
                    artist="巴赫",
                    album="哥德堡变奏曲",
                    year="1741",
                )
            ]
        return []


class ProvidersTest(unittest.TestCase):
    def test_scrape_retries_with_structured_aliases_after_primary_miss(self):
        provider = AliasOnlyProvider()
        local = AlbumMetadata(
            artist="Johann Sebastian Bach",
            album="Goldberg Variations",
            year="1741",
            artist_aliases=["巴赫"],
            album_aliases=["哥德堡變奏曲"],
        )

        candidates, warnings = scrape_candidates(
            local,
            providers=[provider],
            limit_per_source=5,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(provider.calls[-1], ("巴赫", "哥德堡變奏曲"))
        self.assertEqual(candidates[0].source_id, "localized")
        self.assertGreater(candidates[0].score, 0.90)


if __name__ == "__main__":
    unittest.main()

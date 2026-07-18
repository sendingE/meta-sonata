import unittest

from meta_sonata.album_parser import parse_album_dir


class AlbumParserTest(unittest.TestCase):
    def test_parse_inline_artist_and_album_aliases(self):
        md = parse_album_dir(
            "Johann Sebastian Bach (巴赫) - Goldberg Variations (哥德堡變奏曲) (1741) [FLAC]"
        )

        self.assertEqual(md.artist_aliases, ["巴赫"])
        self.assertEqual(md.album_aliases, ["哥德堡變奏曲"])

    def test_parse_common_opencd_folder(self):
        md = parse_album_dir("Scott Joplin - Maple Leaf Rag (Piano Roll Edition) (1899) [WAV]")
        self.assertEqual(md.artist, "Scott Joplin")
        self.assertEqual(md.album, "Maple Leaf Rag")
        self.assertEqual(md.year, "1899")
        self.assertIn("Piano Roll Edition", md.edition)
        self.assertIn("WAV", md.media)
        self.assertGreaterEqual(md.confidence, 0.85)

    def test_parse_leading_index(self):
        md = parse_album_dir("005 Scott Joplin - The Entertainer")
        self.assertEqual(md.artist, "Scott Joplin")
        self.assertEqual(md.album, "The Entertainer")

    def test_parse_year_album_without_artist(self):
        md = parse_album_dir("1899 - Maple Leaf Rag")
        self.assertIsNone(md.artist)
        self.assertEqual(md.album, "Maple Leaf Rag")
        self.assertEqual(md.year, "1899")


if __name__ == "__main__":
    unittest.main()

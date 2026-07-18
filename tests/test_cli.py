import contextlib
import io
import json
import unittest

from meta_sonata.cli import build_parser, cmd_sources


class SourcesCliTest(unittest.TestCase):
    def test_sources_distinguishes_metadata_and_lyrics_capabilities(self):
        args = build_parser().parse_args(["sources"])
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = cmd_sources(args)

        self.assertEqual(result, 0)
        self.assertIn("qmusic       metadata=planned", output.getvalue())
        self.assertIn("lyrics=implemented", output.getvalue())
        self.assertIn("musicbrainz  metadata=implemented", output.getvalue())

    def test_sources_json_exposes_lyrics_capability(self):
        args = build_parser().parse_args(["sources", "--json"])
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = cmd_sources(args)

        rows = {row["name"]: row for row in json.loads(output.getvalue())}
        self.assertEqual(result, 0)
        self.assertTrue(rows["qmusic"]["lyrics_implemented"])
        self.assertFalse(rows["qmusic"]["implemented"])
        self.assertFalse(rows["musicbrainz"]["lyrics_implemented"])


if __name__ == "__main__":
    unittest.main()

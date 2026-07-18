import tempfile
import unittest
from pathlib import Path

from meta_sonata.web import build_child_listing, safe_join


class WebTest(unittest.TestCase):
    def test_safe_join_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(ValueError):
                safe_join(root, "../outside")

    def test_child_listing_hides_ignored_files_and_marks_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            album = root / "Scott Joplin - Maple Leaf Rag"
            album.mkdir()
            (album / "01. Maple Leaf Rag.flac").write_bytes(b"not real flac")
            (album / "._01. Maple Leaf Rag.flac").write_bytes(b"appledouble")
            (album / ".DS_Store").write_bytes(b"ignored")
            (album / "notes.txt").write_text("ignore", encoding="utf-8")

            root_rows = build_child_listing(root)
            self.assertEqual(root_rows[0]["type"], "directory")
            self.assertEqual(root_rows[0]["name"], "Scott Joplin - Maple Leaf Rag")

            album_rows = build_child_listing(root, "Scott Joplin - Maple Leaf Rag")
            self.assertEqual(len(album_rows), 1)
            self.assertEqual(album_rows[0]["type"], "audio")
            self.assertEqual(album_rows[0]["name"], "01. Maple Leaf Rag.flac")


if __name__ == "__main__":
    unittest.main()

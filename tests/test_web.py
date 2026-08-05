import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from mutagen.id3 import ID3, TCON, TIT2, TPE1

from meta_sonata.web import (
    BRAND_ICON_SVG,
    CSS,
    HTML,
    build_child_listing,
    run_server_in_thread,
    safe_join,
    track_detail,
)


class WebTest(unittest.TestCase):
    def test_brand_uses_one_canonical_icon_asset(self):
        self.assertEqual(HTML.count('src="/static/meta-sonata.svg"'), 2)
        self.assertNotIn("mark-top", HTML)
        self.assertIn('stroke="#c9f16f"', BRAND_ICON_SVG)
        self.assertIn('stroke="#fff"', BRAND_ICON_SVG)

    def test_embedded_mode_hides_the_duplicate_web_header(self):
        self.assertIn('has("embedded")', HTML)
        self.assertIn(".embedded .topbar", CSS)
        self.assertIn(".embedded .workspace", CSS)

    def test_desktop_library_columns_have_independent_scroll_containers(self):
        self.assertIn("@media (min-width: 901px)", CSS)
        self.assertIn("height: 100%;\n    overflow: hidden;", CSS)
        self.assertIn("flex: 1;\n    min-height: 0;\n    overflow: hidden;", CSS)
        self.assertIn(".tree,\n  .viewer {\n    overscroll-behavior: contain;", CSS)

    def test_brand_icon_is_served_as_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, url = run_server_in_thread(Path(tmp), port=0)
            try:
                with urlopen(f"{url}static/meta-sonata.svg") as response:
                    self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
                    self.assertEqual(response.read().decode("utf-8"), BRAND_ICON_SVG)
            finally:
                server.shutdown()
                server.server_close()

    def test_web_serves_requested_localization(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, url = run_server_in_thread(Path(tmp), port=0)
            try:
                with urlopen(f"{url}api/i18n?lang=fr-CA") as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["locale"], "fr")
                self.assertEqual(payload["messages"]["web.library"], "Bibliothèque")
            finally:
                server.shutdown()
                server.server_close()

    def test_hidden_utility_overrides_component_display(self):
        self.assertIn(".hidden {\n  display: none !important;\n}", CSS)

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

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_mp3_detail_exposes_canonical_metadata_and_raw_id3_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = root / "Artist - Song.mp3"
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
                    str(track),
                ],
                check=True,
            )
            tags = ID3(track)
            tags.add(TIT2(encoding=3, text=["Song"]))
            tags.add(TPE1(encoding=3, text=["Artist"]))
            tags.add(TCON(encoding=3, text=["Pop"]))
            tags.save(track)

            detail = track_detail(root, track.name)

            self.assertEqual(detail["tags"]["title"], ["Song"])
            self.assertEqual(detail["tags"]["artist"], ["Artist"])
            self.assertEqual(detail["tags"]["genre"], ["Pop"])
            self.assertEqual(detail["raw_tags"]["tit2"], ["Song"])


if __name__ == "__main__":
    unittest.main()

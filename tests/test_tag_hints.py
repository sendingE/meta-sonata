import tempfile
import unittest
import shutil
from pathlib import Path

from mutagen.flac import FLAC

from meta_sonata.scanner import scan_root
from meta_sonata.tag_hints import local_metadata_for_scan


class TagHintsTest(unittest.TestCase):
    def test_existing_tags_fill_missing_artist(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate a temporary FLAC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            album = root / "1899 - Maple Leaf Rag"
            album.mkdir()
            path = album / "01. Maple Leaf Rag.flac"

            # Minimal fake FLAC is not valid, so write tags onto a copy-like FLAC
            # structure is covered by integration smoke tests. Here we use monkey
            # patchable behavior through a real generated file only when ffmpeg is
            # available.
            import subprocess

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
            flac = FLAC(str(path))
            flac["artist"] = "Scott Joplin"
            flac["album"] = "Maple Leaf Rag"
            flac["date"] = "1899"
            flac.save()

            scan = scan_root(album)[0]
            md = local_metadata_for_scan(scan)
            self.assertEqual(md.artist, "Scott Joplin")
            self.assertEqual(md.album, "Maple Leaf Rag")
            self.assertEqual(md.year, "1899")

    def test_existing_tags_take_priority_over_conflicting_folder_metadata(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate a temporary FLAC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            album = root / "Scott Joplin - The Entertainer (1902) [FLAC]"
            album.mkdir()
            path = album / "01. Maple Leaf Rag.flac"

            import subprocess

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
            flac = FLAC(str(path))
            flac["artist"] = "Scott Joplin"
            flac["album"] = "Maple Leaf Rag"
            flac["date"] = "1899"
            flac.save()

            scan = scan_root(album)[0]
            md = local_metadata_for_scan(scan)
            self.assertEqual(md.artist, "Scott Joplin")
            self.assertEqual(md.album, "Maple Leaf Rag")
            self.assertEqual(md.year, "1899")
            self.assertIn("folder_album_conflicts_with_existing_tags", md.warnings)
            self.assertIn("folder_year_conflicts_with_existing_tags", md.warnings)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path

from mutagen.flac import FLAC

from meta_sonata.planner import build_album_plan
from meta_sonata.models import ScrapeCandidate, ScrapedTrack
from meta_sonata.scanner import scan_root


class PlannerTest(unittest.TestCase):
    def test_existing_track_tags_take_priority_over_filename_inference(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate a temporary FLAC")
        with tempfile.TemporaryDirectory() as tmp:
            album = Path(tmp) / "Scott Joplin - Maple Leaf Rag (1899) [FLAC]"
            album.mkdir()
            path = album / "01. Filename Guess.flac"
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
            flac = FLAC(path)
            flac["title"] = "Maple Leaf Rag"
            flac["artist"] = "Scott Joplin"
            flac["album"] = "Maple Leaf Rag"
            flac["tracknumber"] = "01"
            flac["publisher"] = "Public Domain Archive"
            flac.save()

            plan = build_album_plan(scan_root(album)[0])
            tags = plan.tracks[0].tags
            self.assertEqual(tags["title"], "Maple Leaf Rag")
            self.assertEqual(tags["tracknumber"], "01")
            self.assertEqual(tags["label"], "Public Domain Archive")

    def test_scan_and_plan_album_with_disc_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            album = tmp_path / "Scott Joplin - Maple Leaf Rag (1899) [FLAC]"
            disc = album / "Disc 1"
            disc.mkdir(parents=True)
            (disc / "01. Scott Joplin - Maple Leaf Rag.flac").write_bytes(b"not a real flac")
            (album / "Cover.jpg").write_bytes(b"fake image")
            (album / "._ignored.flac").write_bytes(b"ignored")

            scans = scan_root(album)
            self.assertEqual(len(scans), 1)
            self.assertEqual(len(scans[0].audio_files), 1)

            plan = build_album_plan(scans[0])
            self.assertEqual(plan.metadata.artist, "Scott Joplin")
            self.assertEqual(plan.metadata.album, "Maple Leaf Rag")
            self.assertEqual(plan.tracks[0].tags["tracknumber"], "1")
            self.assertEqual(plan.tracks[0].tags["discnumber"], "1")
            self.assertEqual(plan.tracks[0].tags["title"], "Maple Leaf Rag")
            self.assertIsNotNone(plan.cover_file)

    def test_scrape_fills_extra_fields_without_overriding_local_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            album = tmp_path / "Scott Joplin - Maple Leaf Rag (1899) [FLAC]"
            album.mkdir(parents=True)
            (album / "01. Scott Joplin - Maple Leaf Rag.flac").write_bytes(b"not a real flac")

            scan = scan_root(album)[0]
            scraped = ScrapeCandidate(
                provider="musicbrainz",
                source_id="mb-release",
                artist="Scott Joplin",
                album="Maple Leaf Rag",
                year="1899",
                label="Public Domain Archive",
                catalog_number="SAMPLE-1",
                cover_url="https://example.test/cover.jpg",
                tracks=[
                    ScrapedTrack(
                        title="Remote Title Should Not Win",
                        artist="Scott Joplin",
                        tracknumber="1",
                        discnumber="1",
                        source_id="mb-track",
                    )
                ],
                score=0.90,
            )
            plan = build_album_plan(scan, scraped=scraped)
            tags = plan.tracks[0].tags
            self.assertEqual(plan.metadata.artist, "Scott Joplin")
            self.assertEqual(plan.metadata.album, "Maple Leaf Rag")
            self.assertEqual(tags["title"], "Maple Leaf Rag")
            self.assertEqual(tags["label"], "Public Domain Archive")
            self.assertEqual(tags["catalognumber"], "SAMPLE-1")
            self.assertEqual(tags["musicbrainz_albumid"], "mb-release")
            self.assertEqual(tags["musicbrainz_trackid"], "mb-track")
            self.assertEqual(tags["discnumber"], "1")
            self.assertEqual(plan.remote_cover_url, "https://example.test/cover.jpg")


if __name__ == "__main__":
    unittest.main()

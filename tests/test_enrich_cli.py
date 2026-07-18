import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC

from meta_sonata.cli import main
from meta_sonata.lyrics import LyricsEnrichmentReport
from meta_sonata.models import ScrapeCandidate, ScrapedTrack
from meta_sonata.planner import build_album_plan
from meta_sonata.resolver import ResolveResult
from meta_sonata.state import read_state, state_path, write_state


class EnrichCliTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate a temporary FLAC")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.album = self.root / "Scott Joplin - Maple Leaf Rag (1899) [FLAC]"
        self.album.mkdir()
        self.track = self.album / "01. Maple Leaf Rag.flac"
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
                str(self.track),
            ],
            check=True,
        )
        self.state_dir = self.root / "state"

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _resolve(scan, **kwargs):
        candidate = ScrapeCandidate(
            provider="musicbrainz",
            source_id="public-domain-release",
            artist="Scott Joplin",
            album="Maple Leaf Rag",
            year="1899",
            label="Public Domain Archive",
            catalog_number="PD-1899",
            barcode="0000000000000",
            tracks=[
                ScrapedTrack(
                    title="Maple Leaf Rag",
                    artist="Scott Joplin",
                    tracknumber="1",
                    discnumber="1",
                    source_id="public-domain-track",
                )
            ],
            score=1.0,
        )
        return ResolveResult(
            scan=scan,
            candidates=[candidate],
            warnings=[],
            plan=build_album_plan(scan, scraped=candidate, min_scrape_score=kwargs["min_score"]),
        )

    @staticmethod
    def _add_lyrics(plan, **kwargs):
        tracks = [
            replace(
                track,
                tags={
                    **track.tags,
                    "lyrics": "[00:01.00]Public domain test line",
                    "syncedlyrics": "[00:01.00]Public domain test line",
                    "lyrics_source": "test:public-domain",
                    "lyrics_score": "1.000",
                },
            )
            for track in plan.tracks
        ]
        return replace(plan, tracks=tracks), LyricsEnrichmentReport(total=1, found=1)

    def test_enrich_dry_run_calls_scraping_and_lyrics_without_writing(self):
        before = hashlib.sha256(self.track.read_bytes()).digest()
        output = io.StringIO()
        with patch("meta_sonata.cli.resolve_scan", side_effect=self._resolve) as resolve_mock:
            with patch(
                "meta_sonata.cli.enrich_album_plan_with_lyrics",
                side_effect=self._add_lyrics,
            ) as lyrics_mock:
                with redirect_stdout(output):
                    rc = main(["enrich", str(self.album), "--state-dir", str(self.state_dir)])

        self.assertEqual(rc, 0)
        self.assertEqual(hashlib.sha256(self.track.read_bytes()).digest(), before)
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(resolve_mock.call_count, 1)
        self.assertEqual(lyrics_mock.call_count, 1)
        self.assertIn("scan: root=", output.getvalue())
        self.assertIn("files=1 album_groups=1 loose_tracks=0 max_depth=3", output.getvalue())
        self.assertIn("resolve: 1/1", output.getvalue())
        self.assertIn("lyrics: 1/1", output.getvalue())
        self.assertIn("dry run: 1 plan(s)", output.getvalue())
        self.assertIn("lyrics=1/1", output.getvalue())

    def test_enrich_write_persists_tags_and_changed_only_skips_second_run(self):
        output = io.StringIO()
        with patch("meta_sonata.cli.resolve_scan", side_effect=self._resolve) as resolve_mock:
            with patch(
                "meta_sonata.cli.enrich_album_plan_with_lyrics",
                side_effect=self._add_lyrics,
            ) as lyrics_mock:
                with redirect_stdout(output):
                    first_rc = main(
                        ["enrich", str(self.album), "--state-dir", str(self.state_dir), "--write"]
                    )
                    second_rc = main(
                        [
                            "enrich",
                            str(self.album),
                            "--state-dir",
                            str(self.state_dir),
                            "--changed-only",
                            "--write",
                        ]
                    )

        audio = FLAC(self.track)
        self.assertEqual(first_rc, 0)
        self.assertEqual(second_rc, 0)
        self.assertEqual(audio["label"], ["Public Domain Archive"])
        self.assertEqual(audio["catalognumber"], ["PD-1899"])
        self.assertEqual(audio["lyrics_source"], ["test:public-domain"])
        self.assertEqual(audio["syncedlyrics"], ["[00:01.00]Public domain test line"])
        self.assertTrue(state_path(self.album, self.state_dir).exists())
        self.assertEqual(resolve_mock.call_count, 1)
        self.assertEqual(lyrics_mock.call_count, 1)
        self.assertIn("write complete: changed=1 skipped=0", output.getvalue())
        self.assertIn("write complete: changed=0 skipped=0", output.getvalue())

    def test_enrich_disable_switches_do_not_call_online_enrichers(self):
        with patch("meta_sonata.cli.resolve_scan") as resolve_mock:
            with patch("meta_sonata.cli.enrich_album_plan_with_lyrics") as lyrics_mock:
                with redirect_stdout(io.StringIO()):
                    rc = main(["enrich", str(self.album), "--no-scrape", "--no-lyrics"])

        self.assertEqual(rc, 0)
        resolve_mock.assert_not_called()
        lyrics_mock.assert_not_called()

    def test_enrich_passes_requested_depth_to_scanner(self):
        nested = self.root / "one" / "two" / "three" / "four" / "Deep Album"
        nested.mkdir(parents=True)
        deep_track = nested / "01. Aria.flac"
        shutil.copy2(self.track, deep_track)

        shallow_output = io.StringIO()
        recursive_output = io.StringIO()
        with redirect_stdout(shallow_output):
            shallow_rc = main(
                ["enrich", str(self.root), "--no-scrape", "--no-lyrics", "--max-depth", "3"]
            )
        with redirect_stdout(recursive_output):
            recursive_rc = main(
                ["enrich", str(self.root), "--no-scrape", "--no-lyrics", "--recursive"]
            )

        self.assertEqual(shallow_rc, 0)
        self.assertEqual(recursive_rc, 0)
        self.assertIn(
            "files=1 album_groups=1 loose_tracks=0 max_depth=3",
            shallow_output.getvalue(),
        )
        self.assertIn(
            "files=2 album_groups=1 loose_tracks=1 max_depth=unlimited",
            recursive_output.getvalue(),
        )

    def test_audit_json_is_not_polluted_by_progress_output(self):
        output = io.StringIO()
        with patch("meta_sonata.cli.resolve_scan", side_effect=self._resolve):
            with redirect_stdout(output):
                rc = main(["audit", str(self.album), "--scrape"])

        payload = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["album_count"], 1)

    def test_loose_track_write_does_not_infer_album_from_parent_directory(self):
        loose_dir = self.root / "车载音乐2000首"
        loose_dir.mkdir()
        loose_track = loose_dir / "Scott Joplin - Maple Leaf Rag.flac"
        shutil.copy2(self.track, loose_track)

        with redirect_stdout(io.StringIO()):
            rc = main(
                [
                    "enrich",
                    str(loose_dir),
                    "--no-scrape",
                    "--no-lyrics",
                    "--no-state",
                    "--write",
                ]
            )

        audio = FLAC(loose_track)
        self.assertEqual(rc, 0)
        self.assertEqual(audio["artist"], ["Scott Joplin"])
        self.assertEqual(audio["title"], ["Maple Leaf Rag"])
        self.assertNotIn("album", audio)
        self.assertNotIn("albumartist", audio)

    def test_loose_tracks_skip_album_providers_when_scraping_is_enabled(self):
        loose_dir = self.root / "车载音乐2000首"
        loose_dir.mkdir()
        shutil.copy2(self.track, loose_dir / "Scott Joplin - Maple Leaf Rag.flac")

        with patch("meta_sonata.resolver.get_providers") as providers_mock:
            with redirect_stdout(io.StringIO()):
                rc = main(["enrich", str(loose_dir), "--no-lyrics"])

        self.assertEqual(rc, 0)
        providers_mock.assert_not_called()

    def test_mixed_directory_writes_one_aggregated_state_record(self):
        mixed = self.root / "mixed"
        mixed.mkdir()
        tracks = []
        for filename, album, artist in (
            ("a.flac", "Album A", "Artist A"),
            ("b.flac", "Album B", "Artist B"),
            ("Artist C - Loose Song.flac", None, "Artist C"),
        ):
            path = mixed / filename
            shutil.copy2(self.track, path)
            audio = FLAC(path)
            audio["title"] = [path.stem]
            audio["artist"] = [artist]
            audio["tracknumber"] = ["1"]
            if album:
                audio["album"] = [album]
            audio.save()
            tracks.append(path)

        with patch("meta_sonata.cli.write_state", wraps=write_state) as state_mock:
            with redirect_stdout(io.StringIO()):
                rc = main(
                    [
                        "enrich",
                        str(mixed),
                        "--no-scrape",
                        "--no-lyrics",
                        "--state-dir",
                        str(self.state_dir),
                        "--write",
                    ]
                )

        state = read_state(mixed, self.state_dir)
        self.assertEqual(rc, 0)
        self.assertEqual(state_mock.call_count, 1)
        self.assertIsNotNone(state)
        self.assertEqual(state["track_count"], 3)
        self.assertEqual(len(state["units"]), 3)


if __name__ == "__main__":
    unittest.main()

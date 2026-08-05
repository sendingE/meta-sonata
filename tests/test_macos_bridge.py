import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC

from meta_sonata.lyrics import LyricsEnrichmentReport
from meta_sonata.macos_bridge import (
    BridgeError,
    build_parser,
    enrich_audio_copy,
    inspect_audio,
    revert_audio_field,
)
from meta_sonata.track_enrichment import (
    LocalTrackIdentity,
    TrackCandidate,
    TrackResolution,
)


class MacOSBridgeTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "Artist - Song.flac"
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
                str(self.source),
            ],
            check=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_audio_returns_ui_payload(self):
        payload = inspect_audio(self.source)

        self.assertEqual(payload["file"]["name"], self.source.name)
        self.assertEqual(payload["metadata"]["title"], "Artist - Song")
        self.assertTrue(payload["writable"])

    def test_missing_file_uses_a_localizable_error_code(self):
        with self.assertRaises(BridgeError) as context:
            inspect_audio(self.root / "missing.mp3")

        self.assertEqual(context.exception.code, "file_not_found")

    def test_app_library_server_command_uses_a_directory_argument(self):
        args = build_parser().parse_args(["library-server", str(self.root)])

        self.assertEqual(args.command, "library-server")
        self.assertEqual(args.path, str(self.root))

    def test_inspect_audio_exposes_full_lyrics_for_the_mac_viewer(self):
        audio = FLAC(self.source)
        audio["syncedlyrics"] = ["[00:01.00]First line\n[00:02.00]Second line"]
        audio.save()

        payload = inspect_audio(self.source)

        self.assertTrue(payload["lyrics"]["has_synced"])
        self.assertEqual(
            payload["lyrics"]["text"],
            "[00:01.00]First line\n[00:02.00]Second line",
        )

    def test_enrich_creates_copy_and_never_mutates_source(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        candidate = TrackCandidate(
            provider="itunes",
            source_id="123",
            title="Song",
            artist="Artist",
            album="Album",
            album_artist="Artist",
            release_date="2024-01-02",
            genre="Pop",
            track_number="1",
            score=0.99,
        )
        resolution = TrackResolution(
            local=LocalTrackIdentity("Song", "Artist", None, 50),
            candidate=candidate,
            candidates=[candidate],
            warnings=[],
        )
        output_dir = self.root / "output"

        with patch("meta_sonata.macos_bridge.resolve_track", return_value=resolution):
            with patch(
                "meta_sonata.macos_bridge.enrich_album_plan_with_lyrics",
                side_effect=lambda plan, **kwargs: (
                    plan,
                    LyricsEnrichmentReport(total=1, missing=1),
                ),
            ):
                payload = enrich_audio_copy(self.source, output_dir)

        output = Path(payload["output"]["path"])
        audio = FLAC(output)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), before)
        self.assertNotEqual(output, self.source)
        self.assertEqual(audio["title"], ["Song"])
        self.assertEqual(audio["album"], ["Album"])
        self.assertEqual(audio["musicinfo_source"], ["itunes:123"])
        self.assertEqual(payload["match"]["source_id"], "123")

    def test_cover_api_failure_does_not_block_the_output_copy(self):
        candidate = TrackCandidate(
            provider="itunes",
            source_id="123",
            title="Song",
            artist="Artist",
            cover_url="https://example.test/cover.jpg",
            score=0.99,
        )
        resolution = TrackResolution(
            local=LocalTrackIdentity("Song", "Artist", None, 50),
            candidate=candidate,
            candidates=[candidate],
            warnings=[],
        )
        output_dir = self.root / "offline-output"

        with patch("meta_sonata.macos_bridge.resolve_track", return_value=resolution):
            with patch(
                "meta_sonata.macos_bridge.enrich_album_plan_with_lyrics",
                side_effect=lambda plan, **kwargs: (
                    plan,
                    LyricsEnrichmentReport(total=1, errors=1),
                ),
            ):
                with patch(
                    "meta_sonata.macos_bridge.download_cover",
                    side_effect=TimeoutError("offline"),
                ):
                    payload = enrich_audio_copy(self.source, output_dir)

        self.assertTrue(Path(payload["output"]["path"]).is_file())
        self.assertTrue(any(row.startswith("cover_error:") for row in payload["warnings"]))

    def test_revert_field_restores_original_value_in_output_file(self):
        original_audio = FLAC(self.source)
        original_audio["genre"] = ["[60yp.com 分享]"]
        original_audio.save()
        output = self.root / "output.flac"
        shutil.copy2(self.source, output)
        output_audio = FLAC(output)
        output_audio["genre"] = ["Mandopop"]
        output_audio.save()

        payload = revert_audio_field(output, self.source, "genre")

        self.assertTrue(payload["changed"])
        self.assertEqual(FLAC(output)["genre"], ["[60yp.com 分享]"])
        self.assertEqual(payload["output"]["metadata"]["genre"], "[60yp.com 分享]")

    def test_revert_field_removes_value_when_original_was_empty(self):
        output = self.root / "output.flac"
        shutil.copy2(self.source, output)
        output_audio = FLAC(output)
        output_audio["album"] = ["Fetched Album"]
        output_audio.save()

        payload = revert_audio_field(output, self.source, "album")

        self.assertTrue(payload["changed"])
        self.assertNotIn("album", FLAC(output))
        self.assertEqual(payload["output"]["metadata"]["album"], "")

    def test_revert_lyrics_removes_fetched_lyrics_when_original_was_empty(self):
        output = self.root / "output.flac"
        shutil.copy2(self.source, output)
        output_audio = FLAC(output)
        output_audio["lyrics"] = ["[00:01.00]Fetched line"]
        output_audio["syncedlyrics"] = ["[00:01.00]Fetched line"]
        output_audio.save()

        payload = revert_audio_field(output, self.source, "lyrics")

        self.assertTrue(payload["changed"])
        self.assertNotIn("lyrics", FLAC(output))
        self.assertNotIn("syncedlyrics", FLAC(output))
        self.assertFalse(payload["output"]["lyrics"]["has_lyrics"])


if __name__ == "__main__":
    unittest.main()

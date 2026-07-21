import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from meta_sonata.cli import build_parser, main
from meta_sonata.state import (
    PIPELINE_MARKER_NAME,
    STATE_DIR_ENV,
    album_signature,
    default_state_dir,
    has_current_state,
    has_pipeline_marker_since,
    state_path,
    write_state,
)


class StateTest(unittest.TestCase):
    def test_default_state_dir_uses_platformdirs(self):
        expected = Path("/platform/state/meta-sonata")
        with patch.dict(os.environ, {}, clear=True):
            with patch("meta_sonata.state.user_state_path", return_value=expected) as state_path_mock:
                self.assertEqual(default_state_dir(), expected)
        state_path_mock.assert_called_once_with("meta-sonata", appauthor=False)

    def test_custom_state_dir_takes_priority(self):
        home = Path.home()
        env = {
            STATE_DIR_ENV: "~/custom-meta-state",
            "HOME": str(home),
            "USERPROFILE": str(home),
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("meta_sonata.state.user_state_path") as state_path_mock:
                self.assertEqual(default_state_dir(), home / "custom-meta-state")
        state_path_mock.assert_not_called()

    def test_enrich_defaults_to_scraping_and_lyrics(self):
        args = build_parser().parse_args(["enrich", "/music"])
        self.assertTrue(args.scrape)
        self.assertTrue(args.lyrics)
        self.assertFalse(args.write)
        self.assertEqual(args.max_depth, 3)

        disabled = build_parser().parse_args(["enrich", "/music", "--no-scrape", "--no-lyrics"])
        self.assertFalse(disabled.scrape)
        self.assertFalse(disabled.lyrics)

        limited = build_parser().parse_args(["enrich", "/music", "--max-depth", "1"])
        self.assertEqual(limited.max_depth, 1)

        recursive = build_parser().parse_args(["enrich", "/music", "--recursive"])
        self.assertIsNone(recursive.max_depth)

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["enrich", "/music", "--max-depth", "-1"])

    def test_external_state_matches_current_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            album = root / "Scott Joplin - Maple Leaf Rag"
            album.mkdir()
            (album / "01. Scott Joplin - Maple Leaf Rag.flac").write_bytes(b"fake")
            sig = album_signature(album)
            write_state(album, {"album_signature": sig}, state_dir)
            self.assertTrue(state_path(album, state_dir).exists())
            self.assertEqual(list(album.glob("*meta-sonata*")), [])
            self.assertTrue(has_current_state(album, state_dir=state_dir))

            (album / "02. Scott Joplin - The Entertainer.flac").write_bytes(b"fake")
            self.assertFalse(has_current_state(album, state_dir=state_dir))

    def test_pipeline_marker_since_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            album = Path(tmp) / "Scott Joplin - Maple Leaf Rag"
            album.mkdir()
            marker = album / PIPELINE_MARKER_NAME
            marker.write_text("{}", encoding="utf-8")
            os.utime(marker, (1000, 1000))

            self.assertTrue(has_pipeline_marker_since(album, 999))
            self.assertFalse(has_pipeline_marker_since(album, 1001))

    def test_cli_incremental_filter_for_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = root / "Scott Joplin - Maple Leaf Rag"
            old = root / "Scott Joplin - The Entertainer"
            fresh.mkdir()
            old.mkdir()
            (fresh / "01. Scott Joplin - Maple Leaf Rag.flac").write_bytes(b"fake")
            (old / "01. Scott Joplin - The Entertainer.flac").write_bytes(b"fake")

            fresh_marker = fresh / PIPELINE_MARKER_NAME
            old_marker = old / PIPELINE_MARKER_NAME
            fresh_marker.write_text("{}", encoding="utf-8")
            old_marker.write_text("{}", encoding="utf-8")
            os.utime(fresh_marker, (2000, 2000))
            os.utime(old_marker, (1000, 1000))

            state_dir = root / "state"
            with redirect_stdout(io.StringIO()):
                rc = main(["tag", str(root), "--pipeline-marker-since", "1500", "--state-dir", str(state_dir)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

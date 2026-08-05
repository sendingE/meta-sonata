import sqlite3
import tempfile
import unittest
from pathlib import Path

from meta_sonata.catalog import CatalogDatabase


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.library = self.base / "Music"
        self.library.mkdir()
        self.catalog = CatalogDatabase(self.base / "data" / "catalog.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_catalog_uses_root_relative_paths_and_embedded_external_ids(self):
        path = self.library / "Artist" / "Album" / "01 Song.flac"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not-real-audio")

        self.catalog.index_audio_file(
            self.library,
            path,
            tags={
                "title": ["Song"],
                "artist": ["Artist"],
                "album": ["Album"],
                "musicbrainz_artistid": ["artist-mbid"],
                "musicbrainz_recordingid": ["recording-mbid"],
                "musicbrainz_albumid": ["release-mbid"],
            },
        )

        self.assertEqual(
            self.catalog.stats(),
            {"libraries": 1, "files": 1, "entities": 3, "decisions": 0},
        )
        with sqlite3.connect(self.catalog.path) as connection:
            relative = connection.execute("SELECT relative_path FROM files").fetchone()[0]
            external = {
                row[0]
                for row in connection.execute("SELECT external_id FROM external_ids")
            }
        self.assertEqual(relative, "Artist/Album/01 Song.flac")
        self.assertEqual(
            external,
            {"artist-mbid", "recording-mbid", "release-mbid"},
        )

    def test_sync_removes_missing_files_only_after_a_complete_scan(self):
        first = self.library / "one.mp3"
        second = self.library / "two.mp3"
        first.write_bytes(b"one")
        second.write_bytes(b"two")

        initial = self.catalog.sync_library(self.library)
        second.unlink()
        refreshed = self.catalog.sync_library(self.library)

        self.assertEqual(initial["indexed"], 2)
        self.assertEqual(refreshed["removed"], 1)
        self.assertEqual(self.catalog.stats()["files"], 1)

    def test_single_file_refresh_preserves_the_last_complete_scan_marker(self):
        path = self.library / "one.mp3"
        path.write_bytes(b"one")
        self.catalog.sync_library(self.library)

        with sqlite3.connect(self.catalog.path) as connection:
            before = connection.execute(
                "SELECT last_seen_token FROM files WHERE relative_path = 'one.mp3'"
            ).fetchone()[0]

        self.catalog.index_audio_file(self.library, path)

        with sqlite3.connect(self.catalog.path) as connection:
            after = connection.execute(
                "SELECT last_seen_token FROM files WHERE relative_path = 'one.mp3'"
            ).fetchone()[0]
        self.assertTrue(before)
        self.assertEqual(after, before)

    def test_user_decisions_are_durable_catalog_data(self):
        path = self.library / "song.ogg"
        path.write_bytes(b"audio")

        self.catalog.record_decision(
            self.library,
            path,
            field="artist",
            original_value="Jay Chou",
            proposed_value="周杰伦",
            decision="accepted",
            provider="musicbrainz",
            external_id="artist-mbid",
        )

        self.assertEqual(self.catalog.stats()["decisions"], 1)


if __name__ == "__main__":
    unittest.main()

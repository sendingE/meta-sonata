import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from meta_sonata.lyrics import embedded_lyrics
from meta_sonata.tag_writer import set_track_field, set_track_lyrics, write_track
from meta_sonata.web import cover_bytes


class TagWriterFormatsTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cover = self.root / "cover.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=32x32",
                "-frames:v",
                "1",
                str(self.cover),
            ],
            check=True,
        )
        self.tags = {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "albumartist": "Artist",
            "date": "2024-01-02",
            "genre": "Pop",
            "tracknumber": "1/9",
            "discnumber": "1/1",
            "musicinfo_source": "test:1",
            "musicbrainz_recordingid": "recording-mbid",
            "musicbrainz_trackid": "release-track-mbid",
            "syncedlyrics": "[00:01.00]Line",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _audio(self, path: Path, codec: str):
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
                codec,
                str(path),
            ],
            check=True,
        )

    def test_mp3_writes_standard_tags_lyrics_and_cover(self):
        path = self.root / "song.mp3"
        self._audio(path, "libmp3lame")

        changed = write_track(path, self.tags, self.cover)
        audio = ID3(path)

        self.assertTrue(changed)
        self.assertEqual(str(audio["TIT2"]), "Song")
        self.assertEqual(str(audio["TPE1"]), "Artist")
        self.assertEqual(str(audio["TXXX:MUSICINFO_SOURCE"]), "test:1")
        self.assertEqual(
            str(audio["TXXX:MusicBrainz Recording Id"]), "recording-mbid"
        )
        self.assertEqual(
            str(audio["TXXX:MusicBrainz Track Id"]), "release-track-mbid"
        )
        self.assertEqual(embedded_lyrics(path)["syncedlyrics"], "[00:01.00]Line")
        self.assertTrue(audio.getall("APIC"))
        self.assertIsNotNone(cover_bytes(path)[0])

    def test_m4a_writes_standard_tags_lyrics_and_cover(self):
        path = self.root / "song.m4a"
        self._audio(path, "aac")

        changed = write_track(path, self.tags, self.cover)
        audio = MP4(path)

        self.assertTrue(changed)
        self.assertEqual(audio.tags["\xa9nam"], ["Song"])
        self.assertEqual(audio.tags["\xa9ART"], ["Artist"])
        self.assertEqual(audio.tags["trkn"], [(1, 9)])
        self.assertEqual(
            audio.tags["----:com.apple.iTunes:MusicBrainz Recording Id"],
            [b"recording-mbid"],
        )
        self.assertEqual(
            audio.tags["----:com.apple.iTunes:MusicBrainz Track Id"],
            [b"release-track-mbid"],
        )
        self.assertEqual(embedded_lyrics(path)["syncedlyrics"], "[00:01.00]Line")
        self.assertTrue(audio.tags["covr"])
        self.assertIsNotNone(cover_bytes(path)[0])

    def test_mp3_single_field_can_be_restored_or_removed(self):
        path = self.root / "field.mp3"
        self._audio(path, "libmp3lame")
        write_track(path, {"genre": "Wrong", "album": "Fetched"}, None)

        self.assertTrue(set_track_field(path, "genre", "Pop"))
        self.assertTrue(set_track_field(path, "album", None))

        audio = ID3(path)
        self.assertEqual(str(audio["TCON"]), "Pop")
        self.assertNotIn("TALB", audio)

    def test_m4a_single_field_can_be_restored_or_removed(self):
        path = self.root / "field.m4a"
        self._audio(path, "aac")
        write_track(path, {"genre": "Wrong", "album": "Fetched"}, None)

        self.assertTrue(set_track_field(path, "genre", "Pop"))
        self.assertTrue(set_track_field(path, "album", None))

        audio = MP4(path)
        self.assertEqual(audio.tags["\xa9gen"], ["Pop"])
        self.assertNotIn("\xa9alb", audio.tags)

    def test_mp3_lyrics_can_be_removed(self):
        path = self.root / "lyrics.mp3"
        self._audio(path, "libmp3lame")
        write_track(path, {"syncedlyrics": "[00:01.00]Line"}, None)

        self.assertTrue(set_track_lyrics(path, {}))

        self.assertEqual(embedded_lyrics(path), {})


if __name__ == "__main__":
    unittest.main()

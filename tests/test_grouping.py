import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC

from meta_sonata.grouping import group_scan
from meta_sonata.planner import build_loose_plan
from meta_sonata.scanner import scan_album
from meta_sonata.tag_hints import local_metadata_for_scan


class GroupingTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate temporary FLAC files")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "车载音乐2000首"
        self.root.mkdir()
        self.template = Path(self.temp_dir.name) / "template.flac"
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
                str(self.template),
            ],
            check=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_track(self, filename, **tags):
        path = self.root / filename
        shutil.copy2(self.template, path)
        audio = FLAC(path)
        for key, value in tags.items():
            audio[key] = [value]
        audio.save()
        return path

    def test_mixed_directory_splits_album_groups_and_loose_tracks(self):
        first = self.add_track(
            "a1.flac",
            title="Maple Leaf Rag",
            artist="Scott Joplin",
            album="Maple Leaf Rag",
            albumartist="Scott Joplin",
            tracknumber="1",
        )
        second = self.add_track(
            "a2.flac",
            title="The Cascades",
            artist="Scott Joplin",
            album="Maple Leaf Rag",
            albumartist="Scott Joplin",
            tracknumber="2",
        )
        third = self.add_track(
            "b1.flac",
            title="Aria",
            artist="Johann Sebastian Bach",
            album="Goldberg Variations",
            albumartist="Johann Sebastian Bach",
            tracknumber="1",
        )
        loose = self.add_track("Other Artist - Loose Song.flac", title="Loose Song", artist="Other Artist")

        groups = group_scan(scan_album(self.root))

        self.assertEqual([group.kind for group in groups], ["album", "album", "loose"])
        self.assertEqual([len(group.audio_files) for group in groups], [2, 1, 1])
        self.assertEqual(set(groups[0].audio_files), {first, second})
        self.assertEqual(groups[0].group_key, "Scott Joplin - Maple Leaf Rag")
        self.assertEqual(groups[1].audio_files, [third])
        self.assertEqual(groups[2].audio_files, [loose])
        self.assertIsNone(local_metadata_for_scan(groups[0]).year)
        self.assertIsNone(local_metadata_for_scan(groups[1]).year)

    def test_compilation_with_different_track_artists_stays_one_album(self):
        self.add_track(
            "01.flac",
            title="Maple Leaf Rag",
            artist="Scott Joplin",
            album="Public Domain Sampler",
            tracknumber="1",
        )
        self.add_track(
            "02.flac",
            title="Aria",
            artist="Johann Sebastian Bach",
            album="Public Domain Sampler",
            tracknumber="2",
        )

        groups = group_scan(scan_album(self.root))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "album")
        self.assertEqual(len(groups[0].audio_files), 2)
        self.assertEqual(groups[0].group_key, "Various Artists - Public Domain Sampler")

    def test_generic_collection_tag_with_varied_artists_becomes_loose(self):
        self.add_track(
            "01.flac",
            title="Maple Leaf Rag",
            artist="Scott Joplin",
            album="车载音乐2000首",
            tracknumber="1",
        )
        self.add_track(
            "02.flac",
            title="Aria",
            artist="Johann Sebastian Bach",
            album="车载音乐2000首",
            tracknumber="2",
        )

        groups = group_scan(scan_album(self.root))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "loose")
        self.assertEqual(len(groups[0].audio_files), 2)

    def test_duplicate_track_positions_become_loose(self):
        for filename in ("first.flac", "second.flac"):
            self.add_track(
                filename,
                title=filename,
                artist="Scott Joplin",
                album="Maple Leaf Rag",
                tracknumber="1",
            )

        groups = group_scan(scan_album(self.root))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "loose")

    def test_multidisc_paths_disambiguate_duplicate_track_numbers(self):
        for disc_name in ("CD1", "CD2"):
            disc = self.root / disc_name
            disc.mkdir()
            path = disc / "01.flac"
            shutil.copy2(self.template, path)
            audio = FLAC(path)
            audio["title"] = [f"{disc_name} Track"]
            audio["artist"] = ["Scott Joplin"]
            audio["album"] = ["Collected Works"]
            audio["tracknumber"] = ["1"]
            audio.save()

        groups = group_scan(scan_album(self.root))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "album")
        self.assertEqual(len(groups[0].audio_files), 2)

    def test_generic_folder_name_does_not_create_album_identity(self):
        generic = Path(self.temp_dir.name) / "车载 - 音乐合集"
        generic.mkdir()
        shutil.copy2(self.template, generic / "Unknown Song.flac")

        groups = group_scan(scan_album(generic))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "loose")

    def test_matching_album_folder_can_still_fill_missing_year(self):
        album = Path(self.temp_dir.name) / "Scott Joplin - Maple Leaf Rag (1899) [FLAC]"
        album.mkdir()
        path = album / "01.flac"
        shutil.copy2(self.template, path)
        audio = FLAC(path)
        audio["artist"] = ["Scott Joplin"]
        audio["album"] = ["Maple Leaf Rag"]
        audio["tracknumber"] = ["1"]
        audio.save()

        group = group_scan(scan_album(album))[0]

        self.assertEqual(local_metadata_for_scan(group).year, "1899")

    def test_loose_plan_infers_track_identity_without_writing_album_fields(self):
        track = self.add_track("Scott Joplin - Maple Leaf Rag.flac")
        group = group_scan(scan_album(self.root))[0]

        plan = build_loose_plan(group)

        self.assertEqual(group.kind, "loose")
        self.assertEqual(plan.tracks[0].path, track)
        self.assertEqual(plan.tracks[0].tags["artist"], "Scott Joplin")
        self.assertEqual(plan.tracks[0].tags["title"], "Maple Leaf Rag")
        self.assertNotIn("album", plan.tracks[0].tags)
        self.assertNotIn("albumartist", plan.tracks[0].tags)
        self.assertIsNone(plan.cover_file)

    def test_ambiguous_cover_is_not_shared_across_mixed_groups(self):
        (self.root / "Cover.jpg").write_bytes(b"not a real cover")
        self.add_track("a.flac", album="Album A", artist="Artist A", tracknumber="1")
        self.add_track("b.flac", album="Album B", artist="Artist B", tracknumber="1")

        groups = group_scan(scan_album(self.root))

        self.assertEqual(len(groups), 2)
        self.assertTrue(all(group.cover_file is None for group in groups))


if __name__ == "__main__":
    unittest.main()

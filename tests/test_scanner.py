import tempfile
import unittest
from pathlib import Path

from meta_sonata.scanner import scan_root


class ScannerScopeTest(unittest.TestCase):
    def test_scans_immediate_album_directories_and_nested_disc_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "Scott Joplin - Maple Leaf Rag"
            second = root / "Johann Sebastian Bach - Goldberg Variations"
            first.mkdir()
            (second / "CD1").mkdir(parents=True)
            (first / "01. Maple Leaf Rag.flac").write_bytes(b"fake")
            (second / "CD1" / "01. Aria.flac").write_bytes(b"fake")

            scans = scan_root(root)

            self.assertEqual([scan.path for scan in scans], [second, first])
            self.assertEqual(len(scans[0].audio_files), 1)
            self.assertEqual(len(scans[1].audio_files), 1)

    def test_album_path_scans_nested_disc_directories_as_one_album(self):
        with tempfile.TemporaryDirectory() as tmp:
            album = Path(tmp) / "Johann Sebastian Bach - Goldberg Variations"
            (album / "CD1").mkdir(parents=True)
            (album / "CD2").mkdir()
            (album / "CD1" / "01. Aria.flac").write_bytes(b"fake")
            (album / "CD2" / "01. Variation.flac").write_bytes(b"fake")

            scans = scan_root(album)

            self.assertEqual(len(scans), 1)
            self.assertEqual(scans[0].path, album)
            self.assertEqual(len(scans[0].audio_files), 2)

    def test_library_root_discovers_nested_albums_without_merging_artists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "Scott Joplin" / "Maple Leaf Rag"
            second = root / "Johann Sebastian Bach" / "Goldberg Variations"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "01. Maple Leaf Rag.flac").write_bytes(b"fake")
            (second / "01. Aria.flac").write_bytes(b"fake")

            scans = scan_root(root)

            self.assertEqual([scan.path for scan in scans], [second, first])
            self.assertEqual([len(scan.audio_files) for scan in scans], [1, 1])

    def test_artist_directory_can_process_its_immediate_album_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist = Path(tmp) / "Scott Joplin"
            first = artist / "Maple Leaf Rag"
            second = artist / "The Entertainer"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "01. Maple Leaf Rag.flac").write_bytes(b"fake")
            (second / "01. The Entertainer.flac").write_bytes(b"fake")

            self.assertEqual([scan.path for scan in scan_root(artist)], [first, second])

    def test_default_depth_is_three_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            depth_three = root / "genre" / "artist" / "album"
            depth_four = root / "region" / "genre" / "artist" / "deep-album"
            depth_three.mkdir(parents=True)
            depth_four.mkdir(parents=True)
            (depth_three / "01. Aria.flac").write_bytes(b"fake")
            (depth_four / "01. Variation.flac").write_bytes(b"fake")

            self.assertEqual([scan.path for scan in scan_root(root)], [depth_three])
            self.assertEqual(scan_root(root, max_depth=2), [])
            self.assertEqual(
                [scan.path for scan in scan_root(root, max_depth=4)],
                [depth_three, depth_four],
            )

    def test_unlimited_recursion_finds_deep_album(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            album = root / "one" / "two" / "three" / "four" / "five" / "album"
            album.mkdir(parents=True)
            (album / "01. Maple Leaf Rag.flac").write_bytes(b"fake")

            self.assertEqual(scan_root(root), [])
            self.assertEqual([scan.path for scan in scan_root(root, max_depth=None)], [album])

    def test_loose_root_tracks_and_nested_album_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "Scott Joplin" / "Maple Leaf Rag"
            nested.mkdir(parents=True)
            loose = root / "loose.flac"
            nested_track = nested / "01. Maple Leaf Rag.flac"
            loose.write_bytes(b"fake")
            nested_track.write_bytes(b"fake")

            scans = scan_root(root)

            self.assertEqual([scan.path for scan in scans], [root, nested])
            self.assertEqual(scans[0].audio_files, [loose])
            self.assertEqual(scans[1].audio_files, [nested_track])

    def test_symlinked_directories_are_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside" / "album"
            outside.mkdir(parents=True)
            (outside / "01. Aria.flac").write_bytes(b"fake")
            link_root = root / "links"
            link_root.mkdir()
            try:
                (link_root / "linked-album").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are not available")

            self.assertEqual(scan_root(link_root, max_depth=None), [])

    def test_negative_depth_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                scan_root(Path(tmp), max_depth=-1)


if __name__ == "__main__":
    unittest.main()

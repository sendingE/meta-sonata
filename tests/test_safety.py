import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from meta_sonata.cli import main
from meta_sonata.safety import (
    PROTECTED_PATHS_ENV,
    ProtectedPathError,
    assert_write_allowed,
    is_protected_path,
    protected_library_paths,
)


class SafetyTest(unittest.TestCase):
    def test_no_protected_paths_by_default(self):
        with patch.dict(os.environ, {PROTECTED_PATHS_ENV: ""}, clear=False):
            self.assertEqual(protected_library_paths(), ())
            self.assertFalse(is_protected_path("/tmp/any-library"))

    def test_write_guard_rejects_protected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real-library"
            child = root / "Scott Joplin - Maple Leaf Rag"
            with patch.dict(os.environ, {PROTECTED_PATHS_ENV: str(root)}, clear=False):
                self.assertTrue(is_protected_path(child))
                with self.assertRaises(ProtectedPathError):
                    assert_write_allowed(child)

    def test_write_guard_allows_temp_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {PROTECTED_PATHS_ENV: ""}, clear=False):
                assert_write_allowed(Path(tmp))

    def test_cli_write_rejects_protected_path_before_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real-library"
            path = root / "nonexistent-test-album"
            stderr = io.StringIO()
            with patch.dict(os.environ, {PROTECTED_PATHS_ENV: str(root)}, clear=False):
                with redirect_stderr(stderr):
                    rc = main(["tag", str(path), "--write"])
            self.assertEqual(rc, 2)
            self.assertIn("Refusing to write", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

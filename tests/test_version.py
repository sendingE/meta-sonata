import plistlib
import re
import unittest
from pathlib import Path

from meta_sonata import __version__


class VersionTest(unittest.TestCase):
    def test_python_and_macos_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)
        self.assertIsNotNone(match)
        with (root / "macos/MetaSonataMac/Resources/Info.plist").open("rb") as handle:
            app_info = plistlib.load(handle)

        self.assertEqual(match.group(1), __version__)
        self.assertEqual(app_info["CFBundleShortVersionString"], __version__)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest

from theodore.cp2k_cube import __version__


class VersionTest(unittest.TestCase):
    def test_release_metadata_matches_package_version(self):
        repository_root = Path(__file__).resolve().parents[1]
        release_version = (repository_root / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(release_version, __version__)


if __name__ == "__main__":
    unittest.main()

import base64
import configparser
import hashlib
from pathlib import Path
import struct
import unittest

from theodore.cp2k_cube.icon import ICON_PNG_BASE64, TK_WINDOW_CLASS


ROOT = Path(__file__).resolve().parents[1]


def read_desktop(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser["Desktop Entry"]


class DesktopIntegrationTest(unittest.TestCase):
    def test_embedded_runtime_icon_is_a_128_pixel_png(self):
        payload = base64.b64decode(ICON_PNG_BASE64, validate=True)
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", payload[16:24]), (128, 128))
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "2b3505ae6c5f8786956dea756640f14d9fa1d33c3ae6a60544990cf3cd3874e0",
        )

    def test_desktop_entries_match_tk_window_class(self):
        appimage = read_desktop(ROOT / "packaging/appimage/TheoCP2K.desktop")
        source = read_desktop(ROOT / "packaging/linux/TheoCP2K.desktop")
        for entry in (appimage, source):
            self.assertEqual(entry["Icon"], "TheoCP2K")
            self.assertEqual(entry["StartupWMClass"], TK_WINDOW_CLASS)
            self.assertEqual(entry["Terminal"], "false")
        self.assertEqual(appimage["Exec"], "TheoCP2K")
        self.assertEqual(source["Exec"], "theodore-cp2k-gui")


if __name__ == "__main__":
    unittest.main()

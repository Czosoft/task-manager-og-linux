import configparser
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tmog_linux.app import load_theme_preference, save_theme_preference


class AppearancePreferenceTests(unittest.TestCase):
    def test_theme_preference_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tmog-linux" / "settings.ini"
            save_theme_preference("light", path)
            self.assertEqual(load_theme_preference(path), "light")

    def test_invalid_theme_falls_back_to_system(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            parser = configparser.ConfigParser()
            parser["appearance"] = {"theme": "unknown"}
            with path.open("w", encoding="utf-8") as stream:
                parser.write(stream)
            self.assertEqual(load_theme_preference(path), "system")

    def test_missing_file_falls_back_to_system(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.ini"
            self.assertEqual(load_theme_preference(path), "system")


if __name__ == "__main__":
    unittest.main()

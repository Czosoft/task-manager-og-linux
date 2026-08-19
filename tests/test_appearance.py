import configparser
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tmog_linux.app import (
    RESOURCE_GRAPH_MAXIMA,
    graph_fraction,
    graph_maximum,
    load_theme_preference,
    save_theme_preference,
)


class AppearancePreferenceTests(unittest.TestCase):
    def test_resource_sparklines_match_main_graph_scales(self):
        self.assertEqual(RESOURCE_GRAPH_MAXIMA["cpu"], 100.0)
        self.assertEqual(RESOURCE_GRAPH_MAXIMA["memory"], 100.0)
        self.assertEqual(RESOURCE_GRAPH_MAXIMA["thermals"], 110.0)
        self.assertEqual(graph_maximum([46.3], RESOURCE_GRAPH_MAXIMA["cpu"]), 100.0)
        self.assertEqual(graph_maximum([35.4], RESOURCE_GRAPH_MAXIMA["memory"]), 100.0)
        self.assertEqual(graph_maximum([62.0], RESOURCE_GRAPH_MAXIMA["thermals"]), 110.0)

    def test_adaptive_sparklines_use_main_graph_headroom(self):
        self.assertAlmostEqual(graph_maximum([80.0, 100.0], None), 115.0)

    def test_summary_dual_axes_normalize_independently(self):
        self.assertAlmostEqual(graph_fraction(46.6, 100.0), 0.466)
        self.assertAlmostEqual(graph_fraction(55.0, 110.0), 0.5)
        self.assertEqual(graph_fraction(120.0, 110.0), 1.0)
        self.assertEqual(graph_fraction(10.0, 0.0), 0.0)

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

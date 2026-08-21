import configparser
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tmog_linux.app import (
    DATA_TOOLBAR_TABLE_GAP,
    RESOURCE_GRAPH_MAXIMA,
    SIDEBAR_COMPACT_BREAKPOINT,
    SIDEBAR_COMPACT_WIDTH,
    SIDEBAR_FULL_WIDTH,
    SUMMARY_DEFAULT_WINDOW_HEIGHT,
    SUMMARY_VIEWPORT_MARGIN,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    clamped_scroll_value,
    graph_fraction,
    graph_maximum,
    horizontally_scrollable,
    icon_button,
    load_cpu_section_preferences,
    load_theme_preference,
    save_cpu_section_preferences,
    save_theme_preference,
    service_status_visual,
    summary_height_adjustment,
)
from gi.repository import Gtk


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

    def test_default_window_fits_summary_with_ten_pixel_margin(self):
        self.assertEqual(SUMMARY_DEFAULT_WINDOW_HEIGHT, 799)
        self.assertEqual(SUMMARY_VIEWPORT_MARGIN, 10)
        self.assertEqual(summary_height_adjustment(662.0, 593.0), 79)
        self.assertEqual(summary_height_adjustment(662.0, 672.0), 0)
        self.assertEqual(summary_height_adjustment(692.0, 692.0), 0)

    def test_compact_window_limits_preserve_the_regular_default(self):
        self.assertEqual((WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT), (500, 420))
        self.assertEqual(SIDEBAR_COMPACT_WIDTH, 58)
        self.assertEqual(SIDEBAR_FULL_WIDTH, 205)
        self.assertGreater(SIDEBAR_COMPACT_BREAKPOINT, WINDOW_MIN_WIDTH)

    def test_horizontal_toolbars_keep_their_natural_height(self):
        toolbar = Gtk.Box()
        scroller = horizontally_scrollable(toolbar)
        self.assertTrue(scroller.get_propagate_natural_height())
        self.assertFalse(scroller.get_vexpand())
        self.assertTrue(scroller.get_overlay_scrolling())
        self.assertEqual(DATA_TOOLBAR_TABLE_GAP, 10)
        self.assertEqual(scroller.get_margin_bottom(), DATA_TOOLBAR_TABLE_GAP)
        self.assertFalse(toolbar.get_vexpand())
        self.assertEqual(toolbar.get_valign(), Gtk.Align.START)

        button = icon_button("view-refresh-symbolic", "Refresh")
        self.assertTrue(button.get_style_context().has_class("compact-button"))
        self.assertEqual(button.get_valign(), Gtk.Align.CENTER)

    def test_process_scroll_restoration_is_clamped_to_visible_range(self):
        self.assertEqual(clamped_scroll_value(420.0, 0.0, 1000.0, 300.0), 420.0)
        self.assertEqual(clamped_scroll_value(900.0, 0.0, 1000.0, 300.0), 700.0)
        self.assertEqual(clamped_scroll_value(-20.0, 0.0, 1000.0, 300.0), 0.0)

    def test_service_status_visuals_distinguish_tree_expanders(self):
        self.assertEqual(service_status_visual("active", "running", "service"), ("●", "#2da44e"))
        self.assertEqual(service_status_visual("active", "exited", "service"), ("◆", "#2da44e"))
        self.assertEqual(service_status_visual("activating", "start", "service"), ("◆", "#d29922"))
        self.assertEqual(service_status_visual("failed", "failed", "service"), ("!", "#e5484d"))
        self.assertEqual(service_status_visual("inactive", "dead", "service"), ("■", "#8b949e"))
        self.assertEqual(service_status_visual("process", "Sleeping", "process"), ("●", "#3b82f6"))

    def test_theme_preference_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tmog-linux" / "settings.ini"
            save_theme_preference("light", path)
            self.assertEqual(load_theme_preference(path), "light")

    def test_cpu_section_preferences_round_trip_without_overwriting_theme(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tmog-linux" / "settings.ini"
            save_theme_preference("dark", path)
            save_cpu_section_preferences(False, True, path)
            self.assertEqual(load_cpu_section_preferences(path), {"overall": False, "logical": True})
            self.assertEqual(load_theme_preference(path), "dark")

            save_theme_preference("light", path)
            self.assertEqual(load_cpu_section_preferences(path), {"overall": False, "logical": True})

    def test_invalid_cpu_section_preferences_fall_back_to_expanded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            parser = configparser.ConfigParser()
            parser["performance"] = {
                "cpu_overall_expanded": "sometimes",
                "cpu_logical_expanded": "false",
            }
            with path.open("w", encoding="utf-8") as stream:
                parser.write(stream)
            self.assertEqual(load_cpu_section_preferences(path), {"overall": True, "logical": True})

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

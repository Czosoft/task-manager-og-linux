from __future__ import annotations

import configparser
import math
import getpass
import shlex
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402,F401 - registers the PyGObject cairo converter
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .metrics import (
    DiskSnapshot,
    GpuSnapshot,
    LinuxMetricsCollector,
    NetworkInterfaceSnapshot,
    ProcessInfo,
    ServiceInfo,
    SystemSnapshot,
    application_id_from_control_group,
    format_bytes,
    format_duration,
    service_membership_from_control_group,
)


COLORS = {
    "green": (0.31, 0.91, 0.39),
    "orange": (1.0, 0.55, 0.16),
    "yellow": (1.0, 0.86, 0.22),
    "blue": (0.28, 0.51, 1.0),
    "purple": (0.78, 0.29, 1.0),
    "red": (1.0, 0.31, 0.35),
}

CORE_GRAPH_SIZES = {
    "expanded": (108, 86),
    "full": (108, 70),
    "compact": (82, 54),
    "numeric": (62, 34),
}
CORE_GRID_SPACING = 6
CORE_GRID_BOTTOM_GUARD = 12
RESOURCE_GRAPH_MAXIMA = {
    "cpu": 100.0,
    "memory": 100.0,
    "gpu": 100.0,
    "npu": None,
    "disk": 100.0,
    "network": None,
    "energy": None,
    "thermals": 110.0,
}
SUMMARY_DEFAULT_WINDOW_HEIGHT = 799
SUMMARY_VIEWPORT_MARGIN = 10


@dataclass(slots=True)
class ApplicationGroup:
    identifier: str
    name: str
    icon_name: str
    processes: list[ProcessInfo]


DARK_CSS = b"""
* { font-family: Ubuntu, Cantarell, sans-serif; }
window, .app-root { background: #111310; color: #e8ebe5; }
headerbar { background: #171916; color: #f4f6f1; border-bottom: 1px solid #30342e; box-shadow: none; }
headerbar .title { color: #f4f6f1; font-size: 14px; font-weight: 600; }
headerbar .subtitle { color: #aeb5aa; }
headerbar button.titlebutton,
headerbar button.titlebutton:backdrop,
headerbar button.titlebutton image {
    background: transparent;
    border-color: transparent;
    color: #f4f6f1;
    box-shadow: none;
    -gtk-icon-shadow: none;
}
headerbar button.titlebutton:hover { background: #30342e; color: #ffffff; }
headerbar button.titlebutton:active { background: #3b4038; color: #ffffff; }
headerbar button.titlebutton.close:hover { background: #c42b1c; color: #ffffff; }
.header-action { min-height: 28px; border-radius: 4px; background: #272a25; border: 1px solid #3b4038; color: #dce0d8; box-shadow: none; }
.header-action:hover { background: #32362f; color: #ffffff; }
.sidebar { background: #171916; border-right: 1px solid #30342e; }
.brand { font-size: 22px; font-weight: 700; color: #f1f5ed; padding: 18px 16px 3px 16px; }
.brand-subtitle { color: #6fe67c; font-size: 9px; padding: 0 16px 16px 16px; }
.nav-button { background: transparent; border: 0; border-radius: 5px; color: #bec4ba; box-shadow: none; padding: 9px 12px; }
.nav-button:hover { background: #21251f; color: #ffffff; }
.nav-button:checked { background: #243426; color: #8ff09a; border-left: 2px solid #56e768; }
.nav-button image { color: #899087; }
.sidebar-footer { border-top: 1px solid #30342e; color: #777d75; font-size: 10px; padding: 12px 16px; }
.page { background: #111310; padding: 18px; }
.page-title { font-size: 28px; font-weight: 400; color: #f1f4ee; }
.eyebrow { font-size: 9px; color: #65e775; }
.muted { color: #8d938a; }
.small { font-size: 10px; }
.card { background: #1a1c19; border: 1px solid #343832; border-radius: 6px; padding: 10px; }
.card-title { font-size: 14px; font-weight: 500; color: #dfe4db; }
.metric-value { font-size: 24px; font-weight: 400; color: #f3f6f0; }
.green { color: #52e866; }
.orange { color: #ff8c29; }
.yellow { color: #ffdc39; }
.blue { color: #4a82ff; }
.purple { color: #c34bff; }
.red { color: #ff505a; }
.status-live { color: #57ea69; font-size: 10px; }
.toolbar { background: #171916; border-bottom: 1px solid #30342e; padding: 8px 12px; }
.toolbar button, .compact-button { min-height: 28px; border-radius: 4px; background: #272a25; border: 1px solid #3b4038; color: #dce0d8; box-shadow: none; }
.toolbar button:hover, .compact-button:hover { background: #32362f; }
.toolbar button:disabled, .compact-button:disabled { background: #20221f; border-color: #30342e; color: #696e67; }
.collapse-button { min-width: 24px; min-height: 24px; padding: 1px; border-radius: 3px; background: transparent; border: 1px solid #343832; color: #aeb5aa; box-shadow: none; }
.collapse-button:hover { background: #292d27; color: #ffffff; }
.danger-button { background: #492326; color: #ff9298; border-color: #753139; }
entry, searchentry { background: #20231f; color: #f1f4ee; border: 1px solid #3b4038; border-radius: 4px; }
treeview { background: #151714; color: #d7dbd3; border: 0; }
treeview:selected { background: #29442d; color: #ffffff; }
treeview header button { background: #20231f; color: #9da49a; border: 0; border-right: 1px solid #30342e; border-bottom: 1px solid #3a3e37; border-radius: 0; box-shadow: none; min-height: 28px; }
treeview.view row:nth-child(even) { background: #181a17; }
scrollbar { background: #151714; }
scrollbar slider { background: #444940; border-radius: 4px; min-width: 8px; min-height: 8px; }
.stable-scroll scrollbar { background: transparent; min-width: 7px; }
.stable-scroll scrollbar.vertical slider,
.stable-scroll scrollbar.vertical:hover slider {
    background: rgba(91, 98, 87, 0.72);
    border-radius: 3px;
    margin: 1px;
    min-width: 5px;
}
.resource-button { background: transparent; color: #abb1a8; border: 0; border-radius: 4px; box-shadow: none; padding: 10px; }
.resource-button:checked { background: #252b24; color: #ffffff; border-left: 2px solid #53e767; }
.resource-title { font-size: 12px; font-weight: 600; }
.resource-detail { color: #858b82; font-size: 9px; }
.detail-label { color: #7f867c; font-size: 9px; }
.detail-value { color: #e9ede6; font-size: 12px; }
.core-grid, .sensor-flow { background: transparent; }
.sensor-tile { background: #151714; border: 1px solid #574c34; border-radius: 4px; padding: 8px; }
.sensor-name { color: #dfe4db; font-size: 10px; font-weight: 600; }
.sensor-source { color: #857d6d; font-size: 8px; }
.sensor-value { color: #ff9a42; font-size: 16px; }
.section-heading { color: #dfe4db; font-size: 16px; font-weight: 500; }
.provider-badge { background: #172b1a; border: 1px solid #2f7138; border-radius: 4px; color: #69ed78; padding: 4px 8px; font-size: 9px; }
.provider-badge.partial-provider { background: #2b2817; border-color: #71692f; color: #e6d96a; }
.provider-badge.unavailable-provider { background: #20221f; border-color: #4b5048; color: #8b9188; }
.statusbar { border-top: 1px solid #30342e; color: #7f867d; padding: 6px 10px; font-size: 9px; }
.unavailable { color: #6f756d; font-size: 18px; }
.separator { background: #31352f; min-height: 1px; min-width: 1px; }
combobox button { background: #252824; color: #e5e9e1; border: 1px solid #3b4038; }
switch { background: #353a33; }
switch:checked { background: #45bd55; }
progressbar trough { background: #282c27; border: 0; min-height: 5px; }
progressbar progress { background: #53e767; border: 0; min-height: 5px; }
.history-graph, .core-graph { background: #131612; color: #bfc9ba; }
menu, menuitem, popover { background: #20231f; color: #e8ebe5; }
menuitem:hover { background: #30352e; color: #ffffff; }
.process-details-dialog,
.process-details-dialog box,
.process-details-dialog viewport,
.process-details-dialog scrolledwindow { background: #1a1c19; color: #e8ebe5; }
.process-details-dialog scrolledwindow { border: 1px solid #343832; }
.process-details-actions { border-top: 1px solid #343832; padding: 8px; }
"""


LIGHT_CSS = b"""
* { font-family: Inter, "SF Pro Text", "Noto Sans", Ubuntu, Cantarell, sans-serif; }
window, .app-root { background: #f5f5f7; color: #1d1d1f; }
headerbar { background: #fbfbfd; color: #1d1d1f; border-bottom: 1px solid #c9c9ce; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08); }
headerbar .title { color: #1d1d1f; font-size: 14px; font-weight: 600; }
headerbar .subtitle { color: #55585e; }
headerbar button.titlebutton,
headerbar button.titlebutton:backdrop {
    background: transparent;
    border-color: transparent;
    color: #242426;
    box-shadow: none;
    -gtk-icon-shadow: none;
}
headerbar button.titlebutton image { color: #242426; -gtk-icon-shadow: none; }
headerbar button.titlebutton:hover { background: #e5e5ea; color: #000000; }
headerbar button.titlebutton:active { background: #d1d1d6; color: #000000; }
headerbar button.titlebutton.close:hover { background: #c42b1c; color: #ffffff; }
headerbar button.titlebutton.close:hover image { color: #ffffff; }
.header-action { min-height: 28px; border-radius: 5px; background: #ffffff; border: 1px solid #b8bcc3; color: #2c2c2e; box-shadow: 0 1px 1px rgba(0, 0, 0, 0.06); }
.header-action:hover { background: #ececf1; color: #000000; }
.sidebar { background: #ececf0; border-right: 1px solid #c9c9ce; }
.brand { font-size: 22px; font-weight: 700; color: #1d1d1f; padding: 18px 16px 3px 16px; }
.brand-subtitle { color: #187635; font-size: 9px; padding: 0 16px 16px 16px; }
.nav-button { background: transparent; border: 0; border-radius: 6px; color: #3f4248; box-shadow: none; padding: 9px 12px; }
.nav-button:hover { background: #dedee3; color: #1d1d1f; }
.nav-button:checked { background: #dcecff; color: #0057b8; border-left: 2px solid #0a84ff; }
.nav-button image { color: #50545b; }
.nav-button:checked image { color: #0069d9; }
.sidebar-footer { border-top: 1px solid #c9c9ce; color: #5d6066; font-size: 10px; padding: 12px 16px; }
.page { background: #f5f5f7; padding: 18px; }
.page-title { font-size: 28px; font-weight: 400; color: #1d1d1f; }
.eyebrow { font-size: 9px; color: #187635; }
.muted { color: #555960; }
.small { font-size: 10px; }
.card { background: #ffffff; border: 1px solid #c9c9ce; border-radius: 7px; padding: 10px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05); }
.card-title { font-size: 14px; font-weight: 500; color: #2c2c2e; }
.metric-value { font-size: 24px; font-weight: 400; color: #1d1d1f; }
.green { color: #087a2c; }
.orange { color: #bd4500; }
.yellow { color: #765800; }
.blue { color: #005ecb; }
.purple { color: #8e22b7; }
.red { color: #c12735; }
.status-live { color: #087a2c; font-size: 10px; }
.toolbar { background: #ececf0; border-bottom: 1px solid #c9c9ce; padding: 8px 12px; }
.toolbar button, .compact-button { min-height: 28px; border-radius: 5px; background: #ffffff; border: 1px solid #b8bcc3; color: #2c2c2e; box-shadow: 0 1px 1px rgba(0, 0, 0, 0.05); }
.toolbar button:hover, .compact-button:hover { background: #e6e6eb; }
.toolbar button:disabled, .compact-button:disabled { background: #ededf0; border-color: #d2d2d7; color: #98989d; box-shadow: none; }
.collapse-button { min-width: 24px; min-height: 24px; padding: 1px; border-radius: 4px; background: transparent; border: 1px solid #b8bcc3; color: #484b51; box-shadow: none; }
.collapse-button:hover { background: #e6e6eb; color: #1d1d1f; }
.danger-button { background: #fff1f1; color: #b4232d; border-color: #d9a2a6; }
entry, searchentry { background: #ffffff; color: #1d1d1f; border: 1px solid #b8bcc3; border-radius: 5px; }
treeview { background: #ffffff; color: #252527; border: 0; }
treeview:selected { background: #0a78e3; color: #ffffff; }
treeview header button { background: #e8e8ed; color: #3f4248; border: 0; border-right: 1px solid #c9c9ce; border-bottom: 1px solid #bfc0c5; border-radius: 0; box-shadow: none; min-height: 28px; }
treeview.view row:nth-child(even) { background: #f4f4f7; }
scrollbar { background: #eeeeF2; }
scrollbar slider { background: #94979d; border-radius: 4px; min-width: 8px; min-height: 8px; }
.stable-scroll scrollbar { background: transparent; min-width: 7px; }
.stable-scroll scrollbar.vertical slider,
.stable-scroll scrollbar.vertical:hover slider {
    background: rgba(104, 107, 113, 0.74);
    border-radius: 3px;
    margin: 1px;
    min-width: 5px;
}
.resource-button { background: transparent; color: #45484e; border: 0; border-radius: 5px; box-shadow: none; padding: 10px; }
.resource-button:checked { background: #dcecff; color: #0057b8; border-left: 2px solid #0a84ff; }
.resource-title { font-size: 12px; font-weight: 600; }
.resource-detail { color: #555960; font-size: 9px; }
.detail-label { color: #555960; font-size: 9px; }
.detail-value { color: #1d1d1f; font-size: 12px; }
.core-grid, .sensor-flow { background: transparent; }
.sensor-tile { background: #fff9f2; border: 1px solid #d4b98f; border-radius: 6px; padding: 8px; }
.sensor-name { color: #2c2c2e; font-size: 10px; font-weight: 600; }
.sensor-source { color: #665b4d; font-size: 8px; }
.sensor-value { color: #ad4200; font-size: 16px; }
.section-heading { color: #2c2c2e; font-size: 16px; font-weight: 500; }
.provider-badge { background: #e3f5e7; border: 1px solid #7fbd8d; border-radius: 5px; color: #106c2a; padding: 4px 8px; font-size: 9px; }
.provider-badge.partial-provider { background: #fff4ce; border-color: #c8ae4d; color: #675000; }
.provider-badge.unavailable-provider { background: #e9e9ed; border-color: #b8bac0; color: #555960; }
.statusbar { border-top: 1px solid #c9c9ce; color: #555960; padding: 6px 10px; font-size: 9px; }
.unavailable { color: #555960; font-size: 18px; }
.separator { background: #c9c9ce; min-height: 1px; min-width: 1px; }
combobox button { background: #ffffff; color: #1d1d1f; border: 1px solid #b8bcc3; }
switch { background: #b8bac0; }
switch:checked { background: #0a84ff; }
progressbar trough { background: #dedee3; border: 0; min-height: 5px; }
progressbar progress { background: #0a84ff; border: 0; min-height: 5px; }
.history-graph, .core-graph { background: #ffffff; color: #3f4248; }
menu, menuitem, popover { background: #ffffff; color: #1d1d1f; }
menuitem:hover { background: #e5e5ea; color: #000000; }
.process-details-dialog,
.process-details-dialog box,
.process-details-dialog viewport,
.process-details-dialog scrolledwindow { background: #ffffff; color: #1d1d1f; }
.process-details-dialog scrolledwindow { border: 1px solid #c9c9ce; }
.process-details-actions { border-top: 1px solid #c9c9ce; padding: 8px; }
"""


THEME_CHOICES = ("system", "dark", "light")


def rgba(color: tuple[float, float, float], alpha: float = 1.0) -> tuple[float, float, float, float]:
    return color[0], color[1], color[2], alpha


def theme_config_path() -> Path:
    return Path(GLib.get_user_config_dir()) / "tmog-linux" / "settings.ini"


def _read_settings(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError):
        return configparser.ConfigParser()
    return parser


def _write_settings(parser: configparser.ConfigParser, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as stream:
            parser.write(stream)
    except OSError:
        pass


def load_theme_preference(path: Path | None = None) -> str:
    parser = _read_settings(path or theme_config_path())
    preference = parser.get("appearance", "theme", fallback="system").lower()
    return preference if preference in THEME_CHOICES else "system"


def save_theme_preference(preference: str, path: Path | None = None) -> None:
    if preference not in THEME_CHOICES:
        return
    destination = path or theme_config_path()
    parser = _read_settings(destination)
    if not parser.has_section("appearance"):
        parser.add_section("appearance")
    parser.set("appearance", "theme", preference)
    _write_settings(parser, destination)


def load_cpu_section_preferences(path: Path | None = None) -> dict[str, bool]:
    parser = _read_settings(path or theme_config_path())
    try:
        return {
            "overall": parser.getboolean("performance", "cpu_overall_expanded", fallback=True),
            "logical": parser.getboolean("performance", "cpu_logical_expanded", fallback=True),
        }
    except ValueError:
        return {"overall": True, "logical": True}


def save_cpu_section_preferences(
    overall_expanded: bool,
    logical_expanded: bool,
    path: Path | None = None,
) -> None:
    destination = path or theme_config_path()
    parser = _read_settings(destination)
    if not parser.has_section("performance"):
        parser.add_section("performance")
    parser.set("performance", "cpu_overall_expanded", str(overall_expanded).lower())
    parser.set("performance", "cpu_logical_expanded", str(logical_expanded).lower())
    _write_settings(parser, destination)


def style_rgb(widget: Gtk.Widget, *, background: bool = False) -> tuple[float, float, float]:
    style = widget.get_style_context()
    state = style.get_state()
    color = style.get_background_color(state) if background else style.get_color(state)
    return color.red, color.green, color.blue


def theme_alpha(widget: Gtk.Widget, dark: float, light: float) -> float:
    window = widget.get_toplevel()
    return light if getattr(window, "_effective_theme", "dark") == "light" else dark


def graph_maximum(values, fixed_max: float | None) -> float:
    if fixed_max is not None:
        return fixed_max
    return max(1.0, max(values, default=0.0) * 1.15)


def graph_fraction(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(0.0, min(1.0, value / maximum))


def summary_height_adjustment(content_height: float, viewport_height: float) -> int:
    overflow = content_height - viewport_height
    if overflow <= 0:
        return 0
    return math.ceil(overflow + SUMMARY_VIEWPORT_MARGIN)


def clamped_scroll_value(value: float, lower: float, upper: float, page_size: float) -> float:
    return min(max(value, lower), max(lower, upper - page_size))


class HistoryGraph(Gtk.DrawingArea):
    def __init__(self, color: str, max_points: int = 60, fixed_max: float | None = 100.0) -> None:
        super().__init__()
        self.set_size_request(260, 150)
        self.color = COLORS[color]
        self.secondary_color = COLORS["orange"]
        self.fixed_max = fixed_max
        self.primary: deque[float] = deque(maxlen=max_points)
        self.secondary: deque[float] = deque(maxlen=max_points)
        self.get_style_context().add_class("history-graph")
        self.connect("draw", self._draw)

    def add(self, value: float, secondary: float | None = None) -> None:
        self.primary.append(max(0.0, value))
        if secondary is not None:
            self.secondary.append(max(0.0, secondary))
        self.queue_draw()

    def clear(self) -> None:
        self.primary.clear()
        self.secondary.clear()
        self.queue_draw()

    def _line(self, context, values: deque[float], color, width: float, maximum: float, w: float, h: float) -> None:
        if not values:
            return
        points = list(values)
        step = w / max(1, values.maxlen - 1)
        context.set_source_rgba(*rgba(color, 0.95))
        context.set_line_width(width)
        for index, value in enumerate(points):
            x = w - (len(points) - 1 - index) * step
            y = h - graph_fraction(value, maximum) * h
            context.move_to(x, y) if index == 0 else context.line_to(x, y)
        context.stroke()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        context.set_source_rgb(*style_rgb(self, background=True))
        context.paint()
        context.set_line_width(1)
        context.set_source_rgba(*rgba(self.color, theme_alpha(self, 0.13, 0.22)))
        for index in range(1, 8):
            x = index * width / 8
            context.move_to(x, 0)
            context.line_to(x, height)
        for index in range(1, 4):
            y = index * height / 4
            context.move_to(0, y)
            context.line_to(width, y)
        context.stroke()
        observed = list(self.primary) + list(self.secondary)
        maximum = graph_maximum(observed, self.fixed_max)
        self._line(context, self.secondary, self.secondary_color, 1.2, maximum, width, height)
        self._line(context, self.primary, self.color, 1.8, maximum, width, height)
        return False


class DualAxisHistoryGraph(Gtk.DrawingArea):
    def __init__(
        self,
        primary_label: str,
        secondary_label: str,
        primary_max: float = 100.0,
        secondary_max: float = 110.0,
        max_points: int = 60,
    ) -> None:
        super().__init__()
        self.primary_label = primary_label
        self.secondary_label = secondary_label
        self.primary_max = primary_max
        self.secondary_max = secondary_max
        self.primary_color = COLORS["green"]
        self.secondary_color = COLORS["orange"]
        self.primary: deque[float] = deque(maxlen=max_points)
        self.secondary: deque[float] = deque(maxlen=max_points)
        self.set_size_request(360, 245)
        self.get_style_context().add_class("history-graph")
        self.connect("draw", self._draw)

    def add(self, primary: float, secondary: float | None = None) -> None:
        self.primary.append(max(0.0, primary))
        if secondary is not None:
            self.secondary.append(max(0.0, secondary))
        self.queue_draw()

    def clear(self) -> None:
        self.primary.clear()
        self.secondary.clear()
        self.queue_draw()

    @staticmethod
    def _text_width(context, text: str) -> float:
        extents = context.text_extents(text)
        return extents.width if hasattr(extents, "width") else extents[2]

    def _line(
        self,
        context,
        values: deque[float],
        color,
        maximum: float,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        if not values:
            return
        points = list(values)
        step = width / max(1, values.maxlen - 1)
        context.set_source_rgba(*rgba(color, 0.96))
        context.set_line_width(1.8)
        for index, value in enumerate(points):
            point_x = x + width - (len(points) - 1 - index) * step
            point_y = y + height - graph_fraction(value, maximum) * height
            context.move_to(point_x, point_y) if index == 0 else context.line_to(point_x, point_y)
        context.stroke()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        context.set_source_rgb(*style_rgb(self, background=True))
        context.paint()

        left, right, top, bottom = 42.0, 47.0, 31.0, 10.0
        plot_width = max(1.0, width - left - right)
        plot_height = max(1.0, height - top - bottom)

        context.select_font_face("Ubuntu", 0, 0)
        context.set_font_size(9)
        context.set_source_rgba(*rgba(self.primary_color, 0.95))
        context.rectangle(left, 8, 13, 2)
        context.fill()
        context.move_to(left + 18, 13)
        context.show_text(self.primary_label)

        primary_legend_width = self._text_width(context, self.primary_label)
        secondary_x = left + 34 + primary_legend_width
        context.set_source_rgba(*rgba(self.secondary_color, 0.95))
        context.rectangle(secondary_x, 8, 13, 2)
        context.fill()
        context.move_to(secondary_x + 18, 13)
        context.show_text(self.secondary_label)

        context.set_line_width(1)
        context.set_source_rgba(*rgba(self.primary_color, theme_alpha(self, 0.13, 0.22)))
        for index in range(9):
            x = left + index * plot_width / 8
            context.move_to(x, top)
            context.line_to(x, top + plot_height)
        for index in range(5):
            y = top + index * plot_height / 4
            context.move_to(left, y)
            context.line_to(left + plot_width, y)
        context.stroke()

        context.set_source_rgba(*rgba(self.primary_color, theme_alpha(self, 0.5, 0.72)))
        context.rectangle(left + 0.5, top + 0.5, max(1.0, plot_width - 1), max(1.0, plot_height - 1))
        context.stroke()

        for fraction, primary_text, secondary_text in (
            (0.0, "100%", "110 C"),
            (0.5, "50%", "55 C"),
            (1.0, "0%", "0 C"),
        ):
            label_y = top + fraction * plot_height + (9 if fraction == 0.0 else 3 if fraction == 0.5 else -2)
            context.set_source_rgba(*rgba(self.primary_color, 0.9))
            context.move_to(left - 6 - self._text_width(context, primary_text), label_y)
            context.show_text(primary_text)
            context.set_source_rgba(*rgba(self.secondary_color, 0.9))
            context.move_to(left + plot_width + 6, label_y)
            context.show_text(secondary_text)

        self._line(
            context,
            self.secondary,
            self.secondary_color,
            self.secondary_max,
            left,
            top,
            plot_width,
            plot_height,
        )
        self._line(
            context,
            self.primary,
            self.primary_color,
            self.primary_max,
            left,
            top,
            plot_width,
            plot_height,
        )
        return False


class SegmentMeter(Gtk.DrawingArea):
    def __init__(self, label: str, color: str) -> None:
        super().__init__()
        self.label = label
        self.color_name = color
        self.color = COLORS[color]
        self.value = 0.0
        self.value_text = "--"
        self.set_size_request(54, 190)
        self.connect("draw", self._draw)

    def set_value(self, value: float | None, text: str | None = None) -> None:
        self.value = max(0.0, min(100.0, value or 0.0))
        self.value_text = text if text is not None else ("--" if value is None else f"{value:.1f}%")
        self.queue_draw()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        top, bottom = 23.0, height - 27.0
        meter_height = max(40.0, bottom - top)
        segments = 20
        context.select_font_face("Ubuntu", 0, 0)
        context.set_font_size(9)
        context.set_source_rgba(*rgba(self.color, 0.88))
        context.move_to(5, 12)
        context.show_text(self.label.upper())
        for index in range(segments):
            y = bottom - (index + 1) * meter_height / segments
            active = index < math.ceil(self.value / 100.0 * segments)
            context.set_source_rgba(*rgba(self.color, 0.9 if active else theme_alpha(self, 0.12, 0.2)))
            context.rectangle(6, y + 2, width - 12, max(2, meter_height / segments - 3))
            context.fill()
        context.set_font_size(9)
        context.set_source_rgba(*rgba(self.color, 0.95))
        context.move_to(4, height - 7)
        context.show_text(self.value_text[:9])
        return False


class SegmentBar(Gtk.DrawingArea):
    def __init__(self, color: str, segments: int = 30, height: int = 16) -> None:
        super().__init__()
        self.color = COLORS[color]
        self.value = 0.0
        self.segments = segments
        self.set_size_request(160, height)
        self.connect("draw", self._draw)

    def set_value(self, value: float | None) -> None:
        self.value = max(0.0, min(100.0, value or 0.0))
        self.queue_draw()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        gap = 2.0
        segment_width = max(2.0, (width - gap * (self.segments - 1)) / self.segments)
        active_count = math.ceil(self.value / 100.0 * self.segments)
        for index in range(self.segments):
            context.set_source_rgba(
                *rgba(self.color, 0.95 if index < active_count else theme_alpha(self, 0.12, 0.2))
            )
            context.rectangle(index * (segment_width + gap), 1, segment_width, max(2, height - 2))
            context.fill()
        return False


class Sparkline(Gtk.DrawingArea):
    def __init__(self, color: str, points: int = 36, fixed_max: float | None = None) -> None:
        super().__init__()
        self.color = COLORS[color]
        self.fixed_max = fixed_max
        self.values: deque[float] = deque(maxlen=points)
        self.set_size_request(58, 34)
        self.connect("draw", self._draw)

    def add(self, value: float) -> None:
        self.values.append(max(0.0, value))
        self.queue_draw()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        context.set_source_rgba(*rgba(self.color, theme_alpha(self, 0.08, 0.13)))
        context.rectangle(0, 0, width, height)
        context.fill()
        if not self.values:
            return False
        maximum = graph_maximum(self.values, self.fixed_max)
        step = width / max(1, self.values.maxlen - 1)
        context.set_source_rgba(*rgba(self.color, 0.95))
        context.set_line_width(1.4)
        for index, value in enumerate(self.values):
            x = width - (len(self.values) - 1 - index) * step
            y = height - 2 - min(1.0, value / maximum) * (height - 4)
            context.move_to(x, y) if index == 0 else context.line_to(x, y)
        context.stroke()
        return False


class ResourceRow(Gtk.RadioButton):
    def __init__(
        self,
        group: Gtk.RadioButton | None,
        title: str,
        color: str,
        fixed_max: float | None,
    ) -> None:
        Gtk.RadioButton.__init__(self)
        if group:
            self.join_group(group)
        self.set_mode(False)
        self.get_style_context().add_class("resource-button")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.get_style_context().add_class("resource-title")
        title_label.get_style_context().add_class(color)
        self.detail_label = Gtk.Label(label="Waiting for data", xalign=0)
        self.detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail_label.get_style_context().add_class("resource-detail")
        labels.pack_start(title_label, False, False, 0)
        labels.pack_start(self.detail_label, False, False, 0)
        self.sparkline = Sparkline(color, points=60, fixed_max=fixed_max)
        content.pack_start(labels, True, True, 0)
        content.pack_end(self.sparkline, False, False, 0)
        self.add(content)

    def update(self, detail: str, graph_value: float | None) -> None:
        self.detail_label.set_text(detail)
        if graph_value is not None:
            self.sparkline.add(graph_value)


class DetailGrid(Gtk.Grid):
    def __init__(self, keys: list[tuple[str, str]], columns: int = 4) -> None:
        super().__init__(column_spacing=18, row_spacing=10)
        self.value_labels: dict[str, Gtk.Label] = {}
        for index, (key, label) in enumerate(keys):
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            caption = Gtk.Label(label=label, xalign=0)
            caption.get_style_context().add_class("detail-label")
            value = Gtk.Label(label="--", xalign=0)
            value.set_ellipsize(Pango.EllipsizeMode.END)
            value.set_selectable(True)
            value.get_style_context().add_class("detail-value")
            item.pack_start(caption, False, False, 0)
            item.pack_start(value, False, False, 0)
            self.attach(item, index % columns, index // columns, 1, 1)
            self.value_labels[key] = value
        self.set_column_homogeneous(True)

    def update(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            label = self.value_labels.get(key)
            if label:
                label.set_text(value)
                label.set_tooltip_text(value)


class CoreGraph(Gtk.DrawingArea):
    def __init__(self, index: int, core_type: str = "") -> None:
        super().__init__()
        self.index = index
        self.core_type = core_type
        self.color = COLORS["blue"] if core_type == "P" else COLORS["green"]
        self.value = 0.0
        self.values: deque[float] = deque(maxlen=45)
        self.density = "full"
        self.set_size_request(108, 70)
        self.get_style_context().add_class("core-graph")
        self.connect("draw", self._draw)

    def add(self, value: float) -> None:
        self.value = max(0.0, min(100.0, value))
        self.values.append(self.value)
        self.queue_draw()

    def set_density(self, density: str) -> None:
        if density == self.density:
            return
        self.density = density
        width, height = CORE_GRAPH_SIZES[density]
        self.set_size_request(width, height)
        self.queue_draw()

    def _draw(self, _widget, context) -> bool:
        allocation = self.get_allocation()
        width, height = allocation.width, allocation.height
        context.set_source_rgb(*style_rgb(self, background=True))
        context.paint()
        context.set_source_rgba(*rgba(self.color, theme_alpha(self, 0.48, 0.62)))
        context.set_line_width(1)
        context.rectangle(0.5, 0.5, max(1, width - 1), max(1, height - 1))
        context.stroke()
        if self.density == "numeric":
            context.set_source_rgba(*rgba(self.color, 0.35))
            context.rectangle(1, max(1, height - 4), max(0, (width - 2) * self.value / 100.0), 3)
            context.fill()
            context.select_font_face("Ubuntu", 0, 0)
            context.set_font_size(7.5)
            context.set_source_rgb(*style_rgb(self))
            context.move_to(5, height / 2 + 3)
            context.show_text(f"CPU {self.index:02d}")
            context.set_source_rgba(*rgba(self.color, 1.0))
            context.move_to(max(5, width - 25), height / 2 + 3)
            context.show_text(f"{self.value:.0f}%")
            return False

        context.set_source_rgba(*rgba(self.color, theme_alpha(self, 0.12, 0.2)))
        context.set_line_width(1)
        for fraction in (0.25, 0.5, 0.75):
            context.move_to(0, height * fraction)
            context.line_to(width, height * fraction)
        context.stroke()
        if self.values:
            step = width / max(1, self.values.maxlen - 1)
            points = [
                (
                    width - (len(self.values) - 1 - offset) * step,
                    height - 4 - value / 100.0 * (height - 22),
                )
                for offset, value in enumerate(self.values)
            ]
            context.move_to(points[0][0], height)
            for x, y in points:
                context.line_to(x, y)
            context.line_to(points[-1][0], height)
            context.close_path()
            context.set_source_rgba(*rgba(self.color, 0.13))
            context.fill()
            context.set_source_rgba(*rgba(self.color, 0.96))
            context.set_line_width(1.4)
            for offset, (x, y) in enumerate(points):
                context.move_to(x, y) if offset == 0 else context.line_to(x, y)
            context.stroke()
        context.select_font_face("Ubuntu", 0, 0)
        context.set_font_size(7.5 if self.density == "compact" else 8.5)
        context.set_source_rgb(*style_rgb(self))
        context.move_to(6, 12)
        if self.density == "compact" and self.core_type:
            type_text = f" / {self.core_type}"
        else:
            type_text = f" / {self.core_type}-CORE" if self.core_type else ""
        context.show_text(f"CPU {self.index:02d}{type_text}")
        value_text = f"{self.value:.0f}%"
        context.set_source_rgba(*rgba(self.color, 1.0))
        context.move_to(max(6, width - 29), 12)
        context.show_text(value_text)
        return False


class ThermalSensorTile(Gtk.Box):
    def __init__(self, identifier: str, label: str, source: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.identifier = identifier
        self.set_size_request(205, 105)
        self.get_style_context().add_class("sensor-tile")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.name_label = Gtk.Label(label=label, xalign=0)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.set_tooltip_text(label)
        self.name_label.get_style_context().add_class("sensor-name")
        self.source_label = Gtk.Label(label=source.upper(), xalign=0)
        self.source_label.get_style_context().add_class("sensor-source")
        self.value_label = Gtk.Label(label="--", xalign=1)
        self.value_label.get_style_context().add_class("sensor-value")
        labels.pack_start(self.name_label, False, False, 0)
        labels.pack_start(self.source_label, False, False, 0)
        header.pack_start(labels, True, True, 0)
        header.pack_end(self.value_label, False, False, 0)
        self.graph = Sparkline("orange", points=60)
        self.graph.set_size_request(-1, 48)
        self.pack_start(header, False, False, 0)
        self.pack_start(self.graph, True, True, 0)

    def update(self, value: float) -> None:
        self.value_label.set_text(f"{value:.1f} C")
        self.graph.add(value)


class MetricCard(Gtk.Box):
    def __init__(self, title: str, color: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.get_style_context().add_class("card")
        header = Gtk.Label(label=title, xalign=0)
        header.get_style_context().add_class("card-title")
        header.get_style_context().add_class(color)
        self.pack_start(header, False, False, 0)
        self.value = Gtk.Label(label="--", xalign=0)
        self.value.get_style_context().add_class("metric-value")
        self.value.get_style_context().add_class(color)
        self.pack_start(self.value, False, False, 0)
        self.detail = Gtk.Label(label="Waiting for data", xalign=0)
        self.detail.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail.get_style_context().add_class("muted")
        self.detail.get_style_context().add_class("small")
        self.pack_start(self.detail, False, False, 0)
        self.bar = SegmentBar(color, segments=22, height=12)
        self.pack_start(self.bar, False, False, 2)

    def update(self, value: str, detail: str, percent: float | None = None) -> None:
        self.value.set_text(value)
        self.detail.set_text(detail)
        self.detail.set_tooltip_text(detail)
        self.bar.set_value(percent)


def icon_button(icon: str, tooltip: str, css_class: str = "compact-button") -> Gtk.Button:
    button = Gtk.Button()
    button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
    button.set_tooltip_text(tooltip)
    button.get_style_context().add_class(css_class)
    return button


def available_icon_name(*candidates: str) -> str:
    theme = Gtk.IconTheme.get_default()
    if theme is not None:
        for candidate in candidates:
            if theme.has_icon(candidate):
                return candidate
    return candidates[-1]


def card(title: str, child: Gtk.Widget, color: str | None = None) -> Gtk.Box:
    container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    container.get_style_context().add_class("card")
    label = Gtk.Label(label=title, xalign=0)
    label.get_style_context().add_class("card-title")
    if color:
        label.get_style_context().add_class(color)
    container.pack_start(label, False, False, 0)
    container.pack_start(child, True, True, 0)
    return container


def collapsible_card(
    title: str,
    child: Gtk.Widget,
    color: str | None = None,
    *,
    expanded: bool = True,
) -> Gtk.Box:
    container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    container.get_style_context().add_class("card")
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label(label=title, xalign=0)
    label.get_style_context().add_class("card-title")
    if color:
        label.get_style_context().add_class(color)
    toggle = icon_button("go-up-symbolic", f"Collapse {title}", "collapse-button")
    header.pack_start(label, True, True, 0)
    header.pack_end(toggle, False, False, 0)
    section_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    section_body.pack_start(child, True, True, 0)
    container.section_expanded = expanded

    def set_section_expanded(value: bool) -> None:
        container.section_expanded = value
        section_body.set_no_show_all(not value)
        if value:
            section_body.show_all()
        else:
            section_body.hide()
        icon = "go-up-symbolic" if value else "go-down-symbolic"
        action = "Collapse" if value else "Expand"
        toggle.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        toggle.set_tooltip_text(f"{action} {title}")
        container.queue_resize()

    def toggle_section(_button: Gtk.Button) -> None:
        set_section_expanded(not container.section_expanded)

    toggle.connect("clicked", toggle_section)
    container.pack_start(header, False, False, 0)
    container.pack_start(section_body, True, True, 0)
    container.collapse_button = toggle
    container.section_body = section_body
    container.set_section_expanded = set_section_expanded
    set_section_expanded(expanded)
    return container


def scrollable(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.add(child)
    return scroller


def add_text_column(view: Gtk.TreeView, title: str, model_index: int, *, expand: bool = False, width: int = 90) -> None:
    renderer = Gtk.CellRendererText()
    renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
    column = Gtk.TreeViewColumn(title, renderer, text=model_index)
    column.set_sort_column_id(model_index)
    column.set_resizable(True)
    column.set_expand(expand)
    if not expand:
        column.set_min_width(width)
    view.append_column(column)


class TmogWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Task Manager OG // Linux")
        self.set_default_size(1240, SUMMARY_DEFAULT_WINDOW_HEIGHT)
        self.set_size_request(900, 600)
        self.set_icon_name("utilities-system-monitor")
        self.collector = LinuxMetricsCollector()
        self.snapshot: SystemSnapshot | None = None
        self.refresh_seconds = 1
        self._collecting = False
        self._last_process_render = 0.0
        self._last_application_render = 0.0
        self._last_service_render = 0.0
        self._sample_generation = 0
        self._current_user = getpass.getuser()
        self._timer_id: int | None = None
        self._summary_default_fit_enabled = True
        self._summary_default_fit_passes = 0
        self.nav_buttons: dict[str, Gtk.ToggleButton] = {}
        self.process_cpu_bars_enabled = True
        self._services: list[ServiceInfo] = []
        self._service_action_in_progress = False
        self._desktop_apps_by_id: dict[str, Gio.AppInfo] = {}
        self._desktop_apps_by_executable: dict[str, Gio.AppInfo] = {}
        self._load_desktop_application_catalog()
        self._io_histories: dict[
            str,
            dict[str, tuple[deque[float], deque[float], deque[float]]],
        ] = {"disk": {}, "network": {}}
        self.theme_preference = load_theme_preference()
        self.cpu_section_preferences = load_cpu_section_preferences()
        self._cpu_section_persistence_enabled = True
        self._gtk_settings = Gtk.Settings.get_default()
        self._desktop_settings = self._get_desktop_interface_settings()
        self._effective_theme = self._resolve_theme(self.theme_preference)

        self._style_provider = Gtk.CssProvider()
        self._style_provider.load_from_data(DARK_CSS if self._effective_theme == "dark" else LIGHT_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        if self._gtk_settings is not None:
            self._gtk_settings.connect("notify::gtk-theme-name", self._on_system_theme_changed)
            self._gtk_settings.connect("notify::gtk-application-prefer-dark-theme", self._on_system_theme_changed)
        if self._desktop_settings is not None:
            self._desktop_settings.connect("changed::color-scheme", self._on_system_theme_changed)

        header = Gtk.HeaderBar()
        self.headerbar = header
        header.set_show_close_button(True)
        header.props.title = "Task Manager OG // Linux"
        header.props.subtitle = "UNOFFICIAL COMMUNITY BUILD"
        self.live_label = Gtk.Label(label="● LIVE")
        self.live_label.get_style_context().add_class("status-live")
        header.pack_start(self.live_label)
        refresh = icon_button("view-refresh-symbolic", "Refresh now", "header-action")
        refresh.connect("clicked", lambda _button: self.request_update())
        header.pack_end(refresh)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.get_style_context().add_class("app-root")
        self.add(root)
        root.pack_start(self._build_sidebar(), False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        root.pack_start(self.stack, True, True, 0)

        self._build_summary_page()
        self._build_performance_page()
        self._build_applications_page()
        self._build_processes_page()
        self._build_system_page()
        self._build_startup_page()
        self._build_users_page()
        self._build_services_page()
        self._build_settings_page()
        self.show_page("summary")
        self.connect("key-press-event", self._on_key_press)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        GLib.idle_add(self._fit_summary_default_height)
        self.request_update()
        self._timer_id = GLib.timeout_add_seconds(self.refresh_seconds, self._timer_tick)
        threading.Thread(target=self._load_slow_lists, daemon=True).start()

    @staticmethod
    def _get_desktop_interface_settings() -> Gio.Settings | None:
        source = Gio.SettingsSchemaSource.get_default()
        if source is None:
            return None
        schema = source.lookup("org.gnome.desktop.interface", True)
        if schema is None or not schema.has_key("color-scheme"):
            return None
        return Gio.Settings.new_full(schema, None, None)

    def _load_desktop_application_catalog(self) -> None:
        for app_info in Gio.AppInfo.get_all():
            app_id = (app_info.get_id() or "").removesuffix(".desktop").casefold()
            if app_id:
                self._desktop_apps_by_id.setdefault(app_id, app_info)
            executable = app_info.get_executable()
            if executable:
                self._desktop_apps_by_executable.setdefault(Path(executable).name.casefold(), app_info)
            commandline = app_info.get_commandline() or ""
            try:
                command = shlex.split(commandline)
            except ValueError:
                command = commandline.split()
            if command:
                self._desktop_apps_by_executable.setdefault(Path(command[0]).name.casefold(), app_info)

    def _system_prefers_dark(self) -> bool:
        if self._desktop_settings is not None:
            try:
                color_scheme = self._desktop_settings.get_string("color-scheme").lower()
                if color_scheme == "prefer-dark":
                    return True
                if color_scheme == "prefer-light":
                    return False
            except GLib.Error:
                pass
        if self._gtk_settings is None:
            return False
        prefer_dark = bool(self._gtk_settings.get_property("gtk-application-prefer-dark-theme"))
        theme_name = str(self._gtk_settings.get_property("gtk-theme-name") or "").lower()
        return prefer_dark or "dark" in theme_name

    def _resolve_theme(self, preference: str) -> str:
        if preference in ("dark", "light"):
            return preference
        return "dark" if self._system_prefers_dark() else "light"

    def _apply_theme(self, preference: str, *, persist: bool = False) -> None:
        if preference not in THEME_CHOICES:
            return
        self.theme_preference = preference
        if persist:
            save_theme_preference(preference)
        effective_theme = self._resolve_theme(preference)
        if effective_theme == self._effective_theme:
            return
        self._effective_theme = effective_theme
        self._style_provider.load_from_data(DARK_CSS if effective_theme == "dark" else LIGHT_CSS)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.reset_widgets(screen)
        self.queue_draw()

    def _on_system_theme_changed(self, *_args) -> None:
        if self.theme_preference == "system":
            self._apply_theme("system")

    def _fit_summary_default_height(self) -> bool:
        if not self._summary_default_fit_enabled or self._summary_default_fit_passes >= 3:
            return GLib.SOURCE_REMOVE
        adjustment = self.summary_scroller.get_vadjustment()
        missing_height = summary_height_adjustment(
            adjustment.get_upper(), adjustment.get_page_size()
        )
        if missing_height == 0:
            return GLib.SOURCE_REMOVE

        width, height = self.get_size()
        target_height = height + missing_height
        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        if display is not None and gdk_window is not None:
            monitor = display.get_monitor_at_window(gdk_window)
            if monitor is not None:
                workarea = monitor.get_workarea()
                target_height = min(target_height, max(600, workarea.height - 20))
        if target_height <= height:
            return GLib.SOURCE_REMOVE

        self._summary_default_fit_passes += 1
        self.resize(width, target_height)
        GLib.timeout_add(40, self._fit_summary_default_height)
        return GLib.SOURCE_REMOVE

    def _build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_size_request(205, -1)
        sidebar.get_style_context().add_class("sidebar")
        brand = Gtk.Label(label="TMOG // LINUX", xalign=0)
        brand.get_style_context().add_class("brand")
        sidebar.pack_start(brand, False, False, 0)
        subtitle = Gtk.Label(label="NATIVE SYSTEM METRICS", xalign=0)
        subtitle.get_style_context().add_class("brand-subtitle")
        sidebar.pack_start(subtitle, False, False, 0)
        performance_icon = available_icon_name(
            "power-profile-performance-symbolic",
            "network-transmit-receive-symbolic",
            "view-list-symbolic",
        )
        items = [
            ("summary", "Summary", "view-grid-symbolic"),
            ("performance", "Performance", performance_icon),
            ("applications", "Applications", "application-x-executable-symbolic"),
            ("processes", "Processes", "system-run-symbolic"),
            ("system", "System Info", "computer-symbolic"),
            ("startup", "Startup Apps", "media-playback-start-symbolic"),
            ("users", "Users", "system-users-symbolic"),
            ("services", "Services", "preferences-system-symbolic"),
        ]
        group: Gtk.RadioButton | None = None
        for name, label, icon in items:
            button = self._nav_button(label, icon, group)
            if group is None:
                group = button
            button.connect("toggled", self._nav_toggled, name)
            self.nav_buttons[name] = button
            sidebar.pack_start(button, False, False, 2)
        sidebar.pack_start(Gtk.Box(), True, True, 0)
        settings = self._nav_button("Settings", "emblem-system-symbolic", group)
        settings.connect("toggled", self._nav_toggled, "settings")
        self.nav_buttons["settings"] = settings
        sidebar.pack_start(settings, False, False, 4)
        footer = Gtk.Label(label="LINUX PROVIDERS  •  BETA 06", xalign=0)
        footer.get_style_context().add_class("sidebar-footer")
        sidebar.pack_start(footer, False, False, 0)
        return sidebar

    @staticmethod
    def _nav_button(label: str, icon: str, group: Gtk.RadioButton | None = None) -> Gtk.RadioButton:
        button = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton.new(None)
        button.set_mode(False)
        button.get_style_context().add_class("nav-button")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        content.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        button.add(content)
        return button

    def _nav_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if button.get_active():
            self.show_page(name)

    def show_page(self, name: str) -> None:
        self.stack.set_visible_child_name(name)
        button = self.nav_buttons.get(name)
        if button and not button.get_active():
            button.set_active(True)
        if name == "processes" and self.snapshot:
            self._render_processes(self.snapshot.processes)
        if name == "applications" and self.snapshot:
            self._render_applications(self.snapshot.processes)
        if name == "users" and self.snapshot:
            self._render_users(self.snapshot.processes)
        if name == "services" and self.snapshot:
            self._render_services(self._services, self.snapshot.processes)

    @staticmethod
    def _page_box(title: str, eyebrow: str) -> tuple[Gtk.Box, Gtk.Box]:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.get_style_context().add_class("page")
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        small = Gtk.Label(label=eyebrow, xalign=0)
        small.get_style_context().add_class("eyebrow")
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("page-title")
        header.pack_start(small, False, False, 0)
        header.pack_start(heading, False, False, 0)
        page.pack_start(header, False, False, 0)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.pack_start(content, True, True, 0)
        return page, content

    def _build_summary_page(self) -> None:
        page, content = self._page_box("Summary", "SYSTEM SUMMARY  /  LIVE")
        self.summary_page = page
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.summary_grid = grid
        grid.set_vexpand(True)
        grid.set_valign(Gtk.Align.FILL)
        self.summary_scroller = scrollable(grid)
        content.pack_start(self.summary_scroller, True, True, 0)

        meters = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.cpu_meter = SegmentMeter("CPU", "green")
        self.clock_meter = SegmentMeter("Clock", "orange")
        self.temp_meter = SegmentMeter("Temp", "yellow")
        self.gpu_meter = SegmentMeter("GPU", "blue")
        for meter in (self.cpu_meter, self.clock_meter, self.temp_meter, self.gpu_meter):
            meters.pack_start(meter, True, True, 0)
        meter_card = card("Live meters", meters)
        meter_card.set_size_request(250, 320)
        meter_card.set_vexpand(True)
        grid.attach(meter_card, 0, 0, 1, 1)

        cpu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        cpu_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        cpu_title = Gtk.Label(label="CPU Overview", xalign=0)
        cpu_title.get_style_context().add_class("card-title")
        self.cpu_value = Gtk.Label(label="--", xalign=1)
        self.cpu_value.get_style_context().add_class("metric-value")
        self.cpu_value.get_style_context().add_class("green")
        cpu_header.pack_start(cpu_title, True, True, 0)
        cpu_header.pack_end(self.cpu_value, False, False, 0)
        cpu_box.pack_start(cpu_header, False, False, 0)
        self.summary_cpu_graph = DualAxisHistoryGraph("Utilization", "Temperature")
        cpu_box.pack_start(self.summary_cpu_graph, True, True, 0)
        self.cpu_detail = Gtk.Label(label="Waiting for data", xalign=0)
        self.cpu_detail.get_style_context().add_class("muted")
        self.cpu_detail.get_style_context().add_class("small")
        cpu_box.pack_start(self.cpu_detail, False, False, 0)
        cpu_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cpu_card.get_style_context().add_class("card")
        cpu_card.pack_start(cpu_box, True, True, 0)
        cpu_card.set_size_request(390, 320)
        cpu_card.set_hexpand(True)
        cpu_card.set_vexpand(True)
        grid.attach(cpu_card, 1, 0, 1, 1)

        self.top_store = Gtk.ListStore(int, str, float, str)
        top_view = Gtk.TreeView(model=self.top_store)
        top_view.set_headers_visible(True)
        add_text_column(top_view, "PID", 0, width=60)
        add_text_column(top_view, "Name", 1, expand=True)
        self._add_formatted_column(top_view, "CPU", 2, lambda value: f"{value:.1f}%", 65)
        add_text_column(top_view, "Memory", 3, width=85)
        top_scroll = scrollable(top_view)
        top_scroll.set_size_request(315, 280)
        top_card = card("Top CPU processes", top_scroll, "green")
        top_card.set_size_request(315, -1)
        top_card.set_vexpand(True)
        grid.attach(top_card, 2, 0, 1, 1)

        memory_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        memory_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.memory_value = Gtk.Label(label="--", xalign=1)
        self.memory_value.get_style_context().add_class("purple")
        memory_header.pack_start(Gtk.Label(label="Memory utilization", xalign=0), True, True, 0)
        memory_header.pack_end(self.memory_value, False, False, 0)
        memory_box.pack_start(memory_header, False, False, 0)
        memory_live = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.summary_memory_meter = SegmentMeter("MEM", "purple")
        self.summary_memory_meter.set_size_request(52, 120)
        memory_live.pack_start(self.summary_memory_meter, False, False, 0)
        self.summary_memory_graph = HistoryGraph("purple")
        self.summary_memory_graph.set_size_request(-1, 115)
        memory_live.pack_start(self.summary_memory_graph, True, True, 0)
        memory_box.pack_start(memory_live, True, True, 0)
        self.memory_detail = Gtk.Label(label="Waiting for data", xalign=0)
        self.memory_detail.get_style_context().add_class("muted")
        self.memory_detail.get_style_context().add_class("small")
        memory_box.pack_start(self.memory_detail, False, False, 0)
        grid.attach(card("Memory", memory_box, "purple"), 0, 1, 3, 1)

        self.disk_card = MetricCard("DISKS", "green")
        self.network_card = MetricCard("NETWORK", "blue")
        self.power_card = MetricCard("ENERGY / THERMALS", "yellow")
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom.pack_start(self.disk_card, True, True, 0)
        bottom.pack_start(self.network_card, True, True, 0)
        bottom.pack_start(self.power_card, True, True, 0)
        grid.attach(bottom, 0, 2, 3, 1)
        self.summary_status = Gtk.Label(label="LINUX PROVIDERS  /  WAITING FOR FIRST SAMPLE", xalign=0)
        self.summary_status.get_style_context().add_class("statusbar")
        content.pack_end(self.summary_status, False, False, 0)
        self.stack.add_named(page, "summary")

    def _build_performance_page(self) -> None:
        page, content = self._page_box("Performance", "HARDWARE  /  60 SECOND HISTORY")
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.pack_start(body, True, True, 0)
        selector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        selector.set_size_request(220, -1)
        body.pack_start(selector, False, False, 0)
        self.performance_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        body.pack_start(self.performance_stack, True, True, 0)
        self.resource_rows: dict[str, ResourceRow] = {}
        self.perf_widgets: dict[str, dict[str, object]] = {}
        group: ResourceRow | None = None
        resources = [
            ("cpu", "CPU", "green"),
            ("memory", "Memory", "purple"),
            ("gpu", "GPU", "blue"),
            ("npu", "NPU", "red"),
            ("disk", "Disks", "orange"),
            ("network", "Network", "blue"),
            ("energy", "Energy", "yellow"),
            ("thermals", "Thermals", "orange"),
        ]
        for name, label, color in resources:
            button = ResourceRow(group, label, color, RESOURCE_GRAPH_MAXIMA[name])
            button.set_size_request(-1, 54)
            if group is None:
                group = button
                button.set_active(True)
            button.connect("toggled", lambda item, key=name: item.get_active() and self.performance_stack.set_visible_child_name(key))
            self.resource_rows[name] = button
            selector.pack_start(button, False, False, 0)
            self._build_performance_resource(name, label, color)
        self.stack.add_named(page, "performance")

    def _build_performance_resource(self, name: str, title: str, color: str) -> None:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_border_width(1)
        content.set_vexpand(True)
        content.set_valign(Gtk.Align.FILL)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        label = Gtk.Label(label=title, xalign=0)
        label.get_style_context().add_class("section-heading")
        subtitle = Gtk.Label(label="Native Linux provider", xalign=0)
        subtitle.get_style_context().add_class("muted")
        subtitle.get_style_context().add_class("small")
        labels.pack_start(label, False, False, 0)
        labels.pack_start(subtitle, False, False, 0)
        heading.pack_start(labels, True, True, 0)
        badge = Gtk.Label(label="NATIVE PROVIDER")
        badge.get_style_context().add_class("provider-badge")
        heading.pack_end(badge, False, False, 0)
        value = Gtk.Label(label="--", xalign=0)
        value.get_style_context().add_class("metric-value")
        value.get_style_context().add_class(color)
        meter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        meter = SegmentBar(color, segments=32, height=17)
        meter_row.pack_start(meter, True, True, 0)
        meter_row.pack_end(value, False, False, 0)
        header.pack_start(heading, False, False, 0)
        header.pack_start(meter_row, False, False, 0)
        device_combo = None
        if name in ("gpu", "disk", "network"):
            device_combo = Gtk.ComboBoxText()
            device_combo.set_tooltip_text(
                {
                    "gpu": "Select graphics adapter",
                    "disk": "Select a physical disk or combined view",
                    "network": "Select a network interface or combined view",
                }[name]
            )
            if name == "gpu":
                device_combo.connect("changed", self._gpu_selection_changed)
            else:
                device_combo.connect("changed", lambda combo, resource=name: self._io_selection_changed(combo, resource))
            header.pack_start(device_combo, False, False, 0)
        content.pack_start(header, False, False, 4)

        fixed_max = 100.0 if name in ("cpu", "memory", "gpu", "disk") else 110.0 if name == "thermals" else None
        graph = HistoryGraph(color, fixed_max=fixed_max)
        graph_height = 175 if name in ("cpu", "network", "thermals") else 220
        graph.set_size_request(520, graph_height)
        graph_title = {
            "cpu": "Overall utilization / kernel time",
            "memory": "Memory utilization / pressure",
            "gpu": "GPU utilization",
            "npu": "NPU utilization",
            "disk": "Active time",
            "network": "Adaptive bandwidth",
            "energy": "Power history",
            "thermals": "Sensor history",
        }[name]
        graph_card = (
            collapsible_card(
                graph_title,
                graph,
                color,
                expanded=self.cpu_section_preferences["overall"],
            )
            if name == "cpu"
            else card(graph_title, graph, color)
        )
        if name == "cpu":
            self.cpu_overall_section = graph_card
        content.pack_start(graph_card, False, True, 0)

        secondary_graph = None
        composition = None
        if name == "cpu":
            self.core_grid = Gtk.Grid(column_spacing=CORE_GRID_SPACING, row_spacing=CORE_GRID_SPACING)
            self.core_grid.set_column_homogeneous(True)
            self.core_grid.set_row_homogeneous(True)
            self.core_grid.set_hexpand(True)
            self.core_grid.set_valign(Gtk.Align.START)
            self.core_grid.get_style_context().add_class("core-grid")
            self.core_grid.connect("size-allocate", self._on_core_grid_size_allocate)
            self.core_graphs: list[CoreGraph] = []
            self._core_graph_types: list[str] = []
            self._core_grid_density: str | None = None
            self._core_grid_columns: int | None = None
            self._pending_core_grid_layout: tuple[str, int] | None = None
            self._core_grid_layout_source: int | None = None
            self.cpu_logical_section = collapsible_card(
                "Logical processors / per-core history",
                self.core_grid,
                "green",
                expanded=self.cpu_section_preferences["logical"],
            )
            self.cpu_overall_section.collapse_button.connect("clicked", self._on_cpu_section_toggled)
            self.cpu_logical_section.collapse_button.connect("clicked", self._on_cpu_section_toggled)
            content.pack_start(self.cpu_logical_section, False, True, 0)
        elif name in ("disk", "network"):
            secondary_graph = HistoryGraph("green" if name == "disk" else "yellow", fixed_max=None)
            secondary_graph.set_size_request(520, 110 if name == "network" else 160)
            title_text = "Disk transfer rate / read and write" if name == "disk" else "Receive and send throughput"
            content.pack_start(card(title_text, secondary_graph, "green" if name == "disk" else "blue"), False, True, 0)
        elif name == "memory":
            composition = SegmentBar("purple", segments=40, height=22)
            content.pack_start(card("Memory composition", composition, "purple"), False, False, 0)
        elif name == "npu":
            unavailable = Gtk.Label(label="No standard Linux NPU provider detected", xalign=0)
            unavailable.get_style_context().add_class("unavailable")
            content.pack_start(unavailable, False, False, 10)

        detail_keys = {
            "cpu": [("util", "Utilization"), ("speed", "Speed"), ("processes", "Processes"), ("threads", "Threads"),
                    ("handles", "File handles"), ("uptime", "Up time"), ("physical", "Physical cores"), ("logical", "Logical processors"),
                    ("max_speed", "Maximum speed"), ("core_layout", "Core layout"), ("interrupts", "Interrupts"),
                    ("model", "Processor"), ("cache", "Cache topology"), ("switches", "Context switches")],
            "memory": [("used", "In use"), ("available", "Available"), ("committed", "Committed"), ("cached", "Cached"),
                       ("buffers", "Buffers"), ("active", "Active"), ("inactive", "Inactive"), ("slab", "Slab"),
                       ("shared", "Shared"), ("swap", "Swap"), ("pressure", "Pressure avg10"), ("total", "Installed")],
            "gpu": [
                ("adapter", "Adapter"), ("driver", "DRM driver"), ("pci", "PCI address"), ("device_id", "PCI ID"),
                ("usage", "Utilization"), ("source", "Utilization source"), ("frequency", "Graphics frequency"),
                ("max_frequency", "Maximum frequency"), ("memory_mode", "Memory mode"), ("vram_used", "VRAM used"),
                ("vram_total", "VRAM total"), ("render", "Device nodes"), ("temperature", "Temperature"),
                ("power", "Power draw"), ("fan", "Fan speed"),
            ],
            "npu": [("provider", "Provider"), ("state", "State")],
            "disk": [
                ("selection", "Selection"), ("type", "Device type"), ("devices", "Physical disks"),
                ("active", "Active time"), ("read", "Read speed"), ("write", "Write speed"),
                ("read_total", "Read total"), ("write_total", "Write total"),
                ("capacity", "Raw capacity"), ("used", "Mounted used"), ("free", "Mounted free"),
            ],
            "network": [
                ("interface", "Selected interface"), ("type", "Connection type"), ("state", "Link state"),
                ("link", "Link speed"), ("receive", "Receive"), ("send", "Send"),
                ("received_total", "Received total"), ("sent_total", "Sent total"),
                ("hardware", "Hardware address"), ("ipv4", "IPv4 address"), ("ipv6", "IPv6 address"),
                ("mtu", "MTU"), ("interfaces", "Detected interfaces"),
            ],
            "energy": [
                ("power", "Observed power"), ("source", "Measurement source"),
                ("cpu_power", "CPU package"), ("gpu_power", "GPU devices"),
                ("system_power", "System input / battery"), ("state", "Power state"),
                ("charge", "Battery charge"), ("processes", "Tracked processes"),
            ],
            "thermals": [("hotspot", "CPU / observed hotspot"), ("sensors", "Sensors"), ("state", "Thermal state")],
        }[name]
        details = DetailGrid(detail_keys, columns=5 if name == "network" else 4)
        details_card = card("Details", details, color)
        details_card.set_vexpand(False)
        content.pack_start(details_card, False, False, 0)

        sensor_flow = None
        if name == "thermals":
            sensor_flow = Gtk.FlowBox()
            sensor_flow.set_selection_mode(Gtk.SelectionMode.NONE)
            sensor_flow.set_homogeneous(True)
            sensor_flow.set_row_spacing(8)
            sensor_flow.set_column_spacing(8)
            sensor_flow.set_min_children_per_line(2)
            sensor_flow.set_max_children_per_line(3)
            sensor_flow.set_valign(Gtk.Align.START)
            sensor_flow.get_style_context().add_class("sensor-flow")
            self.thermal_sensor_flow = sensor_flow
            self.thermal_sensor_tiles: dict[str, ThermalSensorTile] = {}
            content.pack_start(card("Temperature sensors", sensor_flow, "orange"), False, True, 0)

        impact_rows: list[tuple[Gtk.Label, Gtk.ProgressBar]] = []
        if name == "energy":
            impact_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            for _index in range(5):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                process_label = Gtk.Label(label="--", xalign=0)
                process_label.set_size_request(180, -1)
                process_label.set_ellipsize(Pango.EllipsizeMode.END)
                progress = Gtk.ProgressBar()
                row.pack_start(process_label, False, False, 0)
                row.pack_start(progress, True, True, 0)
                impact_box.pack_start(row, False, False, 0)
                impact_rows.append((process_label, progress))
            content.pack_start(card("Top CPU activity / no per-process power attribution", impact_box, "yellow"), False, False, 0)

        self.perf_widgets[name] = {
            "value": value,
            "subtitle": subtitle,
            "meter": meter,
            "graph": graph,
            "secondary_graph": secondary_graph,
            "details": details,
            "composition": composition if name == "memory" else None,
            "impact_rows": impact_rows,
            "badge": badge,
            "availability": unavailable if name == "npu" else None,
            "device_combo": device_combo,
            "sensor_flow": sensor_flow,
        }
        page_scroll = scrollable(content)
        page_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page_scroll.set_overlay_scrolling(False)
        page_scroll.get_style_context().add_class("stable-scroll")
        self.performance_stack.add_named(page_scroll, name)

    def _build_applications_page(self) -> None:
        page, content = self._page_box("Applications", "DESKTOP GROUPS  /  PROCESS TREES")
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.get_style_context().add_class("toolbar")
        self.application_search = Gtk.SearchEntry()
        self.application_search.set_placeholder_text("Filter application, process, PID or command")
        self.application_search.set_size_request(300, -1)
        self.application_search.connect(
            "search-changed",
            lambda _entry: self._render_applications(self.snapshot.processes) if self.snapshot else None,
        )
        toolbar.pack_start(self.application_search, False, False, 0)
        self.application_count_label = Gtk.Label(label="Waiting for process provider")
        self.application_count_label.get_style_context().add_class("muted")
        toolbar.pack_start(self.application_count_label, False, False, 6)
        toolbar.pack_start(Gtk.Box(), True, True, 0)

        self.application_pause_button = icon_button("media-playback-pause-symbolic", "Pause selected application or process")
        self.application_pause_button.connect("clicked", lambda _button: self._control_application_target("pause"))
        toolbar.pack_start(self.application_pause_button, False, False, 0)
        self.application_resume_button = icon_button("media-playback-start-symbolic", "Resume selected application or process")
        self.application_resume_button.connect("clicked", lambda _button: self._control_application_target("resume"))
        toolbar.pack_start(self.application_resume_button, False, False, 0)
        self.application_end_button = icon_button("media-playback-stop-symbolic", "End selected application or process")
        self.application_end_button.connect("clicked", lambda _button: self._confirm_application_action(False))
        toolbar.pack_start(self.application_end_button, False, False, 0)
        self.application_kill_button = icon_button("process-stop-symbolic", "Force stop selected application or process")
        self.application_kill_button.get_style_context().add_class("danger-button")
        self.application_kill_button.connect("clicked", lambda _button: self._confirm_application_action(True))
        toolbar.pack_start(self.application_kill_button, False, False, 0)
        content.pack_start(toolbar, False, False, 0)

        self.application_store = Gtk.TreeStore(
            str,
            str,
            float,
            GObject.TYPE_UINT64,
            GObject.TYPE_UINT64,
            int,
            GObject.TYPE_UINT64,
            GObject.TYPE_UINT64,
            str,
            object,
            object,
            str,
        )
        self.application_view = Gtk.TreeView(model=self.application_store)
        self.application_view.set_rules_hint(True)
        self.application_view.connect("row-activated", self._application_row_activated)
        self.application_view.connect("button-press-event", self._on_application_button_press)
        self.application_view.connect("popup-menu", self._on_application_popup_menu)
        self.application_view.get_selection().connect("changed", self._application_selection_changed)

        icon_renderer = Gtk.CellRendererPixbuf()
        text_renderer = Gtk.CellRendererText()
        text_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        name_column = Gtk.TreeViewColumn("Application / process")
        name_column.pack_start(icon_renderer, False)
        name_column.pack_start(text_renderer, True)
        name_column.add_attribute(icon_renderer, "icon-name", 8)
        name_column.add_attribute(text_renderer, "text", 0)
        name_column.set_expand(True)
        name_column.set_resizable(True)
        name_column.set_sort_column_id(0)
        self.application_view.append_column(name_column)
        add_text_column(self.application_view, "PID", 1, width=80)
        self._add_formatted_column(self.application_view, "CPU", 2, lambda value: f"{value:.1f}%", 80)
        self._add_formatted_column(self.application_view, "Memory", 3, format_bytes, 100)
        self._add_formatted_column(self.application_view, "Swap", 4, format_bytes, 90)
        add_text_column(self.application_view, "Threads", 5, width=75)
        self._add_formatted_column(self.application_view, "Read", 6, format_bytes, 90)
        self._add_formatted_column(self.application_view, "Write", 7, format_bytes, 90)
        for index in range(8):
            self.application_store.set_sort_func(index, self._compare_tree_rows, index)
        self.application_scroller = scrollable(self.application_view)
        self.application_scroller.set_overlay_scrolling(False)
        self.application_scroller.get_style_context().add_class("stable-scroll")
        content.pack_start(self.application_scroller, True, True, 0)
        self.application_status = Gtk.Label(label="Applications are grouped from desktop metadata, cgroups and process ancestry", xalign=0)
        self.application_status.get_style_context().add_class("statusbar")
        content.pack_start(self.application_status, False, False, 0)
        self._application_selection_changed(self.application_view.get_selection())
        self.stack.add_named(page, "applications")

    def _build_processes_page(self) -> None:
        page, content = self._page_box("Processes", "PROCESS TREE  /  NATIVE SIGNALS")
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.get_style_context().add_class("toolbar")
        self.process_view_combo = Gtk.ComboBoxText()
        for key, label in (
            ("all", "All processes"),
            ("mine", "My processes"),
            ("active", "Active"),
            ("tree", "Process tree"),
        ):
            self.process_view_combo.append(key, label)
        self.process_view_combo.set_active_id("all")
        self.process_view_combo.connect("changed", self._process_view_changed)
        toolbar.pack_start(self.process_view_combo, False, False, 0)
        self.process_search = Gtk.SearchEntry()
        self.process_search.set_placeholder_text("Filter name, PID, user or command")
        self.process_search.set_size_request(280, -1)
        self.process_search.connect("search-changed", lambda _entry: self.process_filter.refilter())
        toolbar.pack_start(self.process_search, False, False, 0)
        self.process_count_label = Gtk.Label(label="-- processes")
        self.process_count_label.get_style_context().add_class("muted")
        toolbar.pack_start(self.process_count_label, False, False, 6)
        toolbar.pack_start(Gtk.Box(), True, True, 0)
        self.follow_selection = Gtk.CheckButton(label="Follow selection")
        self.follow_selection.set_active(True)
        toolbar.pack_start(self.follow_selection, False, False, 0)
        self.process_end_button = Gtk.Button(label="End process")
        self.process_end_button.set_sensitive(False)
        self.process_end_button.connect("clicked", lambda _button: self._confirm_process_action(False))
        toolbar.pack_start(self.process_end_button, False, False, 0)
        self.process_kill_button = Gtk.Button(label="Force stop")
        self.process_kill_button.set_sensitive(False)
        self.process_kill_button.get_style_context().add_class("danger-button")
        self.process_kill_button.connect("clicked", lambda _button: self._confirm_process_action(True))
        toolbar.pack_start(self.process_kill_button, False, False, 0)
        content.pack_start(toolbar, False, False, 0)

        self.process_store = Gtk.ListStore(
            int,
            str,
            str,
            str,
            float,
            GObject.TYPE_UINT64,
            int,
            GObject.TYPE_UINT64,
            GObject.TYPE_UINT64,
            str,
            str,
            object,
            int,
        )
        self.process_filter = self.process_store.filter_new()
        self.process_filter.set_visible_func(self._process_visible)
        self._process_sort_preference = (4, Gtk.SortType.DESCENDING)
        self._changing_process_sort = False
        self.process_sort = Gtk.TreeModelSort(model=self.process_filter)
        self.process_sort.set_sort_column_id(*self._process_sort_preference)
        self.process_sort.connect("sort-column-changed", self._process_sort_changed)
        self.process_view = Gtk.TreeView(model=self.process_sort)
        self.process_view.set_rules_hint(True)
        self.process_view.connect("row-activated", self._show_process_details)
        self.process_view.connect("button-press-event", self._on_process_button_press)
        self.process_view.connect("popup-menu", self._on_process_popup_menu)
        self.process_view.get_selection().connect("changed", self._process_selection_changed)
        add_text_column(self.process_view, "PID", 0, width=75)
        add_text_column(self.process_view, "Name", 1, expand=True)
        add_text_column(self.process_view, "User", 2, width=110)
        add_text_column(self.process_view, "Status", 3, width=95)
        self._add_process_cpu_column()
        self._add_formatted_column(self.process_view, "Memory", 5, format_bytes, 95)
        add_text_column(self.process_view, "Threads", 6, width=75)
        self._add_formatted_column(self.process_view, "Read", 7, format_bytes, 88)
        self._add_formatted_column(self.process_view, "Write", 8, format_bytes, 88)
        add_text_column(self.process_view, "Started", 9, width=130)
        add_text_column(self.process_view, "Command", 10, expand=True)
        self.process_scroller = scrollable(self.process_view)
        content.pack_start(self.process_scroller, True, True, 0)
        self.process_status = Gtk.Label(label="Waiting for process provider", xalign=0)
        self.process_status.get_style_context().add_class("statusbar")
        content.pack_start(self.process_status, False, False, 0)
        self.stack.add_named(page, "processes")

    @staticmethod
    def _add_formatted_column(view: Gtk.TreeView, title: str, index: int, formatter, width: int) -> None:
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(title, renderer)
        column.set_sort_column_id(index)
        column.set_resizable(True)
        column.set_min_width(width)

        def render(_column, cell, model, tree_iter, _data=None):
            cell.set_property("text", formatter(model.get_value(tree_iter, index)))

        column.set_cell_data_func(renderer, render)
        view.append_column(column)

    def _add_process_cpu_column(self) -> None:
        text_renderer = Gtk.CellRendererText()
        bar_renderer = Gtk.CellRendererProgress()
        column = Gtk.TreeViewColumn("CPU")
        column.set_sort_column_id(4)
        column.set_resizable(True)
        column.set_min_width(90)
        column.pack_start(text_renderer, True)
        column.pack_start(bar_renderer, True)

        def render_text(_column, cell, model, tree_iter, _data=None):
            value = float(model.get_value(tree_iter, 4))
            cell.set_property("visible", not self.process_cpu_bars_enabled)
            cell.set_property("text", f"{value:.1f}%")

        def render_bar(_column, cell, model, tree_iter, _data=None):
            value = max(0.0, min(100.0, float(model.get_value(tree_iter, 4))))
            cell.set_property("visible", self.process_cpu_bars_enabled)
            cell.set_property("value", int(round(value)))
            cell.set_property("text", f"{value:.1f}%")

        column.set_cell_data_func(text_renderer, render_text)
        column.set_cell_data_func(bar_renderer, render_bar)
        self.process_view.append_column(column)

    def _build_system_page(self) -> None:
        page, content = self._page_box("System Info", "HOST  /  OPERATING SYSTEM")
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for key, value in self.collector.system_information():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            row.set_border_width(10)
            key_label = Gtk.Label(label=key, xalign=0)
            key_label.set_size_request(180, -1)
            key_label.get_style_context().add_class("muted")
            value_label = Gtk.Label(label=value, xalign=0)
            value_label.set_selectable(True)
            value_label.set_line_wrap(True)
            value_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            row.pack_start(key_label, False, False, 0)
            row.pack_start(value_label, True, True, 0)
            info_box.pack_start(row, False, False, 0)
            separator = Gtk.Separator()
            separator.get_style_context().add_class("separator")
            info_box.pack_start(separator, False, False, 0)
        content.pack_start(card("Machine identity", info_box, "blue"), False, False, 0)
        self.system_runtime = MetricCard("RUNTIME", "green")
        self.system_load = MetricCard("LOAD AVERAGE", "orange")
        runtime_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        runtime_row.pack_start(self.system_runtime, True, True, 0)
        runtime_row.pack_start(self.system_load, True, True, 0)
        content.pack_start(runtime_row, False, False, 0)
        self.stack.add_named(page, "system")

    def _build_startup_page(self) -> None:
        page, content = self._page_box("Startup Apps", "XDG AUTOSTART  /  MANAGED")
        note = Gtk.Label(
            label="System entries are managed through safe per-user XDG overrides",
            xalign=0,
        )
        note.get_style_context().add_class("muted")
        content.pack_start(note, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.get_style_context().add_class("toolbar")
        self.startup_count_label = Gtk.Label(label="Loading startup entries...")
        self.startup_count_label.get_style_context().add_class("muted")
        toolbar.pack_start(self.startup_count_label, True, True, 0)

        self.startup_enable_button = Gtk.Button(label="Enable")
        self.startup_enable_button.set_image(
            Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        )
        self.startup_enable_button.set_always_show_image(True)
        self.startup_enable_button.set_sensitive(False)
        self.startup_enable_button.connect("clicked", lambda _button: self._set_startup_enabled(True))
        toolbar.pack_start(self.startup_enable_button, False, False, 0)

        self.startup_disable_button = Gtk.Button(label="Disable")
        self.startup_disable_button.set_image(
            Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON)
        )
        self.startup_disable_button.set_always_show_image(True)
        self.startup_disable_button.set_sensitive(False)
        self.startup_disable_button.connect("clicked", lambda _button: self._set_startup_enabled(False))
        toolbar.pack_start(self.startup_disable_button, False, False, 0)

        open_location = Gtk.Button(label="Open location")
        open_location.set_image(Gtk.Image.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON))
        open_location.set_always_show_image(True)
        open_location.set_sensitive(False)
        open_location.connect("clicked", self._open_startup_location)
        self.startup_open_button = open_location
        toolbar.pack_start(open_location, False, False, 0)

        refresh = icon_button("view-refresh-symbolic", "Refresh startup entries")
        refresh.connect("clicked", lambda _button: self._refresh_startup_entries())
        toolbar.pack_start(refresh, False, False, 0)
        content.pack_start(toolbar, False, False, 0)

        self.startup_store = Gtk.ListStore(str, str, str, str, GObject.TYPE_PYOBJECT)
        self.startup_view = Gtk.TreeView(model=self.startup_store)
        add_text_column(self.startup_view, "Name", 0, expand=True)
        add_text_column(self.startup_view, "Status", 1, width=90)
        add_text_column(self.startup_view, "Source", 2, width=110)
        add_text_column(self.startup_view, "Command", 3, expand=True)
        self.startup_view.get_selection().connect("changed", self._startup_selection_changed)
        content.pack_start(scrollable(self.startup_view), True, True, 0)
        self.stack.add_named(page, "startup")

    def _build_users_page(self) -> None:
        page, content = self._page_box("Users", "PROCESS OWNERS  /  LIVE")
        self.user_store = Gtk.ListStore(str, int, float, GObject.TYPE_UINT64)
        view = Gtk.TreeView(model=self.user_store)
        add_text_column(view, "User", 0, expand=True)
        add_text_column(view, "Processes", 1, width=100)
        self._add_formatted_column(view, "CPU", 2, lambda value: f"{value:.1f}%", 90)
        self._add_formatted_column(view, "Memory", 3, format_bytes, 110)
        content.pack_start(scrollable(view), True, True, 0)
        self.stack.add_named(page, "users")

    def _build_services_page(self) -> None:
        page, content = self._page_box("Services", "SYSTEMD  /  USER + SYSTEM CONTROL")
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.get_style_context().add_class("toolbar")
        self.service_scope_combo = Gtk.ComboBoxText()
        for key, label in (
            ("all", "All services"),
            ("user", "User services"),
            ("system", "System services"),
            ("active", "Active only"),
            ("failed", "Failed only"),
        ):
            self.service_scope_combo.append(key, label)
        self.service_scope_combo.set_active_id("all")
        self.service_scope_combo.connect("changed", lambda _combo: self._render_current_services())
        toolbar.pack_start(self.service_scope_combo, False, False, 0)
        self.service_search = Gtk.SearchEntry()
        self.service_search.set_placeholder_text("Filter unit, state, description or process")
        self.service_search.set_size_request(300, -1)
        self.service_search.connect("search-changed", lambda _entry: self._render_current_services())
        toolbar.pack_start(self.service_search, False, False, 0)
        self.service_count_label = Gtk.Label(label="Loading systemd services...")
        self.service_count_label.get_style_context().add_class("muted")
        toolbar.pack_start(self.service_count_label, False, False, 6)
        toolbar.pack_start(Gtk.Box(), True, True, 0)

        self.service_start_button = icon_button("media-playback-start-symbolic", "Start selected service")
        self.service_start_button.connect("clicked", lambda _button: self._confirm_service_action("start"))
        toolbar.pack_start(self.service_start_button, False, False, 0)
        self.service_stop_button = icon_button("media-playback-stop-symbolic", "Stop selected service")
        self.service_stop_button.get_style_context().add_class("danger-button")
        self.service_stop_button.connect("clicked", lambda _button: self._confirm_service_action("stop"))
        toolbar.pack_start(self.service_stop_button, False, False, 0)
        self.service_restart_button = icon_button(
            available_icon_name("media-playlist-repeat-symbolic", "view-refresh-symbolic"),
            "Restart selected service",
        )
        self.service_restart_button.connect("clicked", lambda _button: self._confirm_service_action("restart"))
        toolbar.pack_start(self.service_restart_button, False, False, 0)
        self.service_details_button = icon_button(
            available_icon_name("document-properties-symbolic", "dialog-information-symbolic"),
            "Show service details",
        )
        self.service_details_button.connect("clicked", lambda _button: self._open_selected_service_details())
        toolbar.pack_start(self.service_details_button, False, False, 0)
        refresh = icon_button("view-refresh-symbolic", "Refresh service units")
        refresh.connect("clicked", lambda _button: self._refresh_services())
        toolbar.pack_start(refresh, False, False, 0)
        content.pack_start(toolbar, False, False, 0)

        self.service_store = Gtk.TreeStore(
            str,
            str,
            str,
            str,
            float,
            GObject.TYPE_UINT64,
            str,
            object,
            object,
            str,
            str,
        )
        self.service_view = Gtk.TreeView(model=self.service_store)
        self.service_view.set_rules_hint(True)
        self.service_view.connect("row-activated", self._service_row_activated)
        self.service_view.connect("button-press-event", self._on_service_button_press)
        self.service_view.connect("popup-menu", self._on_service_popup_menu)
        self.service_view.get_selection().connect("changed", self._service_selection_changed)

        icon_renderer = Gtk.CellRendererPixbuf()
        text_renderer = Gtk.CellRendererText()
        text_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        unit_column = Gtk.TreeViewColumn("Service / process")
        unit_column.pack_start(icon_renderer, False)
        unit_column.pack_start(text_renderer, True)
        unit_column.add_attribute(icon_renderer, "icon-name", 10)
        unit_column.add_attribute(text_renderer, "text", 0)
        unit_column.set_expand(True)
        unit_column.set_resizable(True)
        unit_column.set_sort_column_id(0)
        self.service_view.append_column(unit_column)
        add_text_column(self.service_view, "PID", 1, width=75)
        add_text_column(self.service_view, "Active", 2, width=85)
        add_text_column(self.service_view, "State", 3, width=90)
        self._add_formatted_column(self.service_view, "CPU", 4, lambda value: f"{value:.1f}%", 78)
        self._add_formatted_column(self.service_view, "Memory", 5, format_bytes, 100)
        add_text_column(self.service_view, "Description", 6, expand=True)
        for index in range(7):
            self.service_store.set_sort_func(index, self._compare_service_tree_rows, index)
        self.service_scroller = scrollable(self.service_view)
        self.service_scroller.set_overlay_scrolling(False)
        self.service_scroller.get_style_context().add_class("stable-scroll")
        content.pack_start(self.service_scroller, True, True, 0)
        self.service_status = Gtk.Label(label="Service controls use the current systemd and polkit permissions", xalign=0)
        self.service_status.get_style_context().add_class("statusbar")
        content.pack_start(self.service_status, False, False, 0)
        self._service_initial_render_done = False
        self._service_selection_changed(self.service_view.get_selection())
        self.stack.add_named(page, "services")

    def _build_settings_page(self) -> None:
        page, content = self._page_box("Settings", "DISPLAY  /  SAMPLING")
        appearance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        theme_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        theme_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        theme_labels.pack_start(Gtk.Label(label="Application theme", xalign=0), False, False, 0)
        theme_hint = Gtk.Label(label="Follow AnduinOS / Ubuntu, or keep a fixed appearance", xalign=0)
        theme_hint.get_style_context().add_class("muted")
        theme_labels.pack_start(theme_hint, False, False, 0)
        theme_row.pack_start(theme_labels, True, True, 0)
        self.theme_combo = Gtk.ComboBoxText()
        self.theme_combo.append("system", "Follow system")
        self.theme_combo.append("dark", "Dark")
        self.theme_combo.append("light", "Light")
        self.theme_combo.set_active_id(self.theme_preference)
        self.theme_combo.connect("changed", self._theme_changed)
        theme_row.pack_end(self.theme_combo, False, False, 0)
        appearance_box.pack_start(theme_row, False, False, 0)
        content.pack_start(card("Appearance", appearance_box, "blue"), False, False, 0)

        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.pack_start(Gtk.Label(label="Refresh interval", xalign=0), False, False, 0)
        hint = Gtk.Label(label="How often Linux providers are sampled", xalign=0)
        hint.get_style_context().add_class("muted")
        labels.pack_start(hint, False, False, 0)
        row.pack_start(labels, True, True, 0)
        combo = Gtk.ComboBoxText()
        for seconds in (1, 2, 5):
            combo.append(str(seconds), f"{seconds} second" + ("s" if seconds > 1 else ""))
        combo.set_active_id("1")
        combo.connect("changed", self._refresh_changed)
        row.pack_end(combo, False, False, 0)
        settings_box.pack_start(row, False, False, 0)

        cpu_bar_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        cpu_bar_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cpu_bar_labels.pack_start(Gtk.Label(label="Process CPU pressure bars", xalign=0), False, False, 0)
        cpu_bar_hint = Gtk.Label(label="Show live utilization bars in the Processes CPU column", xalign=0)
        cpu_bar_hint.get_style_context().add_class("muted")
        cpu_bar_labels.pack_start(cpu_bar_hint, False, False, 0)
        cpu_bar_row.pack_start(cpu_bar_labels, True, True, 0)
        cpu_bar_switch = Gtk.Switch()
        cpu_bar_switch.set_active(self.process_cpu_bars_enabled)
        cpu_bar_switch.set_valign(Gtk.Align.CENTER)
        cpu_bar_switch.connect("notify::active", self._process_cpu_bars_changed)
        cpu_bar_row.pack_end(cpu_bar_switch, False, False, 0)
        settings_box.pack_start(cpu_bar_row, False, False, 0)
        content.pack_start(card("Live updates", settings_box, "green"), False, False, 0)
        about = Gtk.Label(
            label=(
                "This is an independent, unofficial Linux implementation inspired by the public TMOG interface.\n"
                "It contains no source code or assets from the official application."
            ),
            xalign=0,
        )
        about.set_line_wrap(True)
        about.get_style_context().add_class("muted")
        content.pack_start(card("About this build", about, "blue"), False, False, 0)
        self.stack.add_named(page, "settings")

    def _theme_changed(self, combo: Gtk.ComboBoxText) -> None:
        preference = combo.get_active_id()
        if preference:
            self._apply_theme(preference, persist=True)

    def _refresh_changed(self, combo: Gtk.ComboBoxText) -> None:
        value = combo.get_active_id()
        if value:
            self.refresh_seconds = int(value)
            if self._timer_id is not None:
                GLib.source_remove(self._timer_id)
            self._timer_id = GLib.timeout_add_seconds(self.refresh_seconds, self._timer_tick)
            self.request_update()

    def _process_cpu_bars_changed(self, switch: Gtk.Switch, _parameter) -> None:
        self.process_cpu_bars_enabled = switch.get_active()
        self.process_view.queue_draw()

    def _timer_tick(self) -> bool:
        self.request_update()
        return GLib.SOURCE_CONTINUE

    def request_update(self) -> None:
        if self._collecting:
            return
        self._collecting = True
        self.live_label.set_text("● SAMPLING")

        def work() -> None:
            try:
                snapshot = self.collector.collect()
                GLib.idle_add(self._apply_snapshot, snapshot)
            except Exception as error:  # Keep the monitor alive if a provider disappears.
                GLib.idle_add(self._collection_failed, str(error))

        threading.Thread(target=work, daemon=True).start()

    def _collection_failed(self, message: str) -> bool:
        self._collecting = False
        self.live_label.set_text("● PROVIDER ERROR")
        self.live_label.set_tooltip_text(message)
        return GLib.SOURCE_REMOVE

    def _apply_snapshot(self, snapshot: SystemSnapshot) -> bool:
        self.snapshot = snapshot
        self._collecting = False
        self._sample_generation += 1
        self.live_label.set_text("● LIVE")
        self.live_label.set_tooltip_text(datetime.fromtimestamp(snapshot.timestamp).strftime("Updated %H:%M:%S"))

        cpu = snapshot.cpu_percent
        memory_percent = 100.0 * snapshot.memory_used / snapshot.memory_total if snapshot.memory_total else 0.0
        observed_temperature = (
            snapshot.temperature_c
            if snapshot.temperature_c is not None
            else max((sensor.temperature_c for sensor in snapshot.thermal_sensors), default=None)
        )
        self.cpu_meter.set_value(cpu)
        clock_percent = (
            100.0 * (snapshot.cpu_mhz or 0.0) / snapshot.cpu_max_mhz
            if snapshot.cpu_max_mhz
            else None
        )
        self.clock_meter.set_value(clock_percent, f"{(snapshot.cpu_mhz or 0) / 1000:.2f}G")
        self.temp_meter.set_value(observed_temperature, "--" if observed_temperature is None else f"{observed_temperature:.0f} C")
        gpu_usages = [gpu.utilization for gpu in snapshot.gpus if gpu.utilization is not None]
        gpu_peak = max(gpu_usages) if gpu_usages else None
        self.gpu_meter.set_value(gpu_peak, "--" if gpu_peak is None else f"{gpu_peak:.0f}%")
        self.cpu_value.set_text(f"{cpu:.1f}%")
        temperature_detail = (
            f"Hotspot {observed_temperature:.1f} C"
            if observed_temperature is not None
            else "Temperature N/A"
        )
        self.cpu_detail.set_text(
            f"{len(snapshot.per_cpu_percent)} logical processors  •  "
            f"{(snapshot.cpu_mhz or 0) / 1000:.2f} GHz  •  {temperature_detail}  •  "
            f"Kernel {snapshot.kernel_percent:.1f}%"
        )
        self.summary_cpu_graph.add(cpu, observed_temperature)
        self.memory_value.set_text(f"{format_bytes(snapshot.memory_used)} / {format_bytes(snapshot.memory_total)}")
        self.memory_detail.set_text(
            f"Available {format_bytes(snapshot.memory_available)}  •  Cached {format_bytes(snapshot.memory_cached)}  •  "
            f"Swap {format_bytes(snapshot.swap_used)} / {format_bytes(snapshot.swap_total)}"
        )
        self.summary_memory_graph.add(memory_percent)
        self.summary_memory_meter.set_value(memory_percent)
        self.disk_card.update(
            f"{snapshot.disk_busy_percent:.1f}%",
            f"Read {format_bytes(snapshot.disk_read_bps, rate=True)}  •  Write {format_bytes(snapshot.disk_write_bps, rate=True)}",
            snapshot.disk_busy_percent,
        )
        network_rate = snapshot.network_receive_bps + snapshot.network_send_bps
        network_percent = self._network_utilization(snapshot, network_rate)
        self.network_card.update(
            format_bytes(network_rate, rate=True),
            f"Receive {format_bytes(snapshot.network_receive_bps, rate=True)}  •  Send {format_bytes(snapshot.network_send_bps, rate=True)}",
            network_percent,
        )
        energy_value = (
            f"{snapshot.observed_power_watts:.1f} W"
            if snapshot.observed_power_watts is not None
            else "POWER SENSOR N/A"
        )
        if snapshot.temperature_c is not None:
            temp_detail = f"CPU hotspot {snapshot.temperature_c:.1f} C"
        elif observed_temperature is not None:
            temp_detail = f"Observed hotspot {observed_temperature:.1f} C"
        else:
            temp_detail = "Thermal sensor unavailable"
        self.power_card.update(energy_value, f"{snapshot.power_source}  •  {temp_detail}", observed_temperature)
        available_providers = 4
        available_providers += int(bool(snapshot.gpus))
        available_providers += int(snapshot.npu_name is not None)
        available_providers += int(snapshot.observed_power_watts is not None)
        available_providers += int(bool(snapshot.thermal_sensors))
        self.summary_status.set_text(
            f"GEN {self._sample_generation:05d}  /  {available_providers}/8 PROVIDERS LIVE  /  "
            f"{snapshot.process_count} PROCESSES  /  {datetime.fromtimestamp(snapshot.timestamp).strftime('%H:%M:%S')}"
        )
        self._render_top_processes(snapshot.processes)
        self._update_performance(snapshot, memory_percent)
        self.system_runtime.update(format_duration(snapshot.uptime_seconds), f"{snapshot.process_count} processes  •  {snapshot.thread_count} threads")
        self.system_load.update("  ".join(f"{value:.2f}" for value in snapshot.load_average), "1, 5 and 15 minute load averages")
        visible = self.stack.get_visible_child_name()
        if visible == "processes" and time.monotonic() - self._last_process_render >= self.refresh_seconds * 0.8:
            self._render_processes(snapshot.processes)
        elif visible == "applications" and time.monotonic() - self._last_application_render >= self.refresh_seconds * 0.8:
            self._render_applications(snapshot.processes)
        elif visible == "services" and time.monotonic() - self._last_service_render >= self.refresh_seconds * 1.8:
            self._render_services(self._services, snapshot.processes)
        elif visible == "users":
            self._render_users(snapshot.processes)
        return GLib.SOURCE_REMOVE

    def _render_top_processes(self, processes: list[ProcessInfo]) -> None:
        self.top_store.clear()
        for process in sorted(processes, key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)[:12]:
            self.top_store.append((process.pid, process.name, round(process.cpu_percent, 1), format_bytes(process.memory_bytes)))

    def _update_performance(self, snapshot: SystemSnapshot, memory_percent: float) -> None:
        self._record_io_histories(snapshot)
        disk_rate = snapshot.disk_read_bps + snapshot.disk_write_bps
        network_rate = snapshot.network_receive_bps + snapshot.network_send_bps
        gpu_usages = [gpu.utilization for gpu in snapshot.gpus if gpu.utilization is not None]
        gpu_peak = max(gpu_usages) if gpu_usages else None
        gpu_text = f"{gpu_peak:.1f}% peak" if gpu_peak is not None else "N/A"
        gpu_detail = (
            f"{len(snapshot.gpus)} adapter{'s' if len(snapshot.gpus) != 1 else ''}  •  {gpu_text}"
            if snapshot.gpus
            else "No graphics provider"
        )
        npu_text = "Detected" if snapshot.npu_name else "N/A"
        power_text = (
            f"{snapshot.observed_power_watts:.1f} W"
            if snapshot.observed_power_watts is not None
            else "N/A"
        )
        observed_temperature = (
            snapshot.temperature_c
            if snapshot.temperature_c is not None
            else max((sensor.temperature_c for sensor in snapshot.thermal_sensors), default=None)
        )
        thermal_text = f"{observed_temperature:.1f} C" if observed_temperature is not None else "N/A"

        resource_values = {
            "cpu": (f"{snapshot.cpu_percent:.1f}%  •  {(snapshot.cpu_mhz or 0) / 1000:.2f} GHz", snapshot.cpu_percent),
            "memory": (f"{memory_percent:.1f}%  •  {format_bytes(snapshot.memory_used)}", memory_percent),
            "gpu": (gpu_detail, gpu_peak),
            "npu": (f"{npu_text}  •  {snapshot.npu_name or 'No provider'}", None),
            "disk": (f"{snapshot.disk_busy_percent:.1f}%  •  {format_bytes(disk_rate, rate=True)}", snapshot.disk_busy_percent),
            "network": (f"{format_bytes(network_rate, rate=True)}  •  {snapshot.primary_interface}", network_rate),
            "energy": (f"{power_text}  •  {snapshot.power_source}", snapshot.observed_power_watts),
            "thermals": (f"{thermal_text}  •  {snapshot.thermal_sensor_count} sensors", observed_temperature),
        }
        for name, (detail, graph_value) in resource_values.items():
            self.resource_rows[name].update(detail, graph_value)

        cpu = self.perf_widgets["cpu"]
        cpu["value"].set_text(f"{snapshot.cpu_percent:.1f}%")
        cpu["subtitle"].set_text(snapshot.cpu_model)
        cpu["meter"].set_value(snapshot.cpu_percent)
        cpu["graph"].add(snapshot.cpu_percent, snapshot.kernel_percent)
        p_cores = snapshot.cpu_core_types.count("P")
        e_cores = snapshot.cpu_core_types.count("E")
        core_layout = (
            f"P {p_cores} logical  •  E {e_cores} logical"
            if p_cores or e_cores
            else "Homogeneous / not reported"
        )
        cpu["details"].update({
            "util": f"{snapshot.cpu_percent:.1f}%",
            "speed": f"{(snapshot.cpu_mhz or 0) / 1000:.2f} GHz" if snapshot.cpu_mhz else "N/A",
            "processes": str(snapshot.process_count),
            "threads": str(snapshot.thread_count),
            "handles": f"{snapshot.file_handle_count:,}",
            "uptime": format_duration(snapshot.uptime_seconds),
            "physical": str(snapshot.cpu_physical_cores),
            "logical": str(len(snapshot.per_cpu_percent)),
            "max_speed": f"{snapshot.cpu_max_mhz / 1000:.2f} GHz" if snapshot.cpu_max_mhz else "N/A",
            "core_layout": core_layout,
            "interrupts": f"{snapshot.interrupts:,}",
            "model": snapshot.cpu_model,
            "cache": snapshot.cpu_cache_summary,
            "switches": f"{snapshot.context_switches:,}",
        })

        memory = self.perf_widgets["memory"]
        memory["value"].set_text(f"{memory_percent:.1f}%")
        memory["subtitle"].set_text(f"{format_bytes(snapshot.memory_total)} installed")
        memory["meter"].set_value(memory_percent)
        memory["graph"].add(memory_percent, snapshot.memory_pressure_percent)
        memory["composition"].set_value(memory_percent)
        memory["details"].update({
            "used": format_bytes(snapshot.memory_used),
            "available": format_bytes(snapshot.memory_available),
            "committed": format_bytes(snapshot.memory_committed),
            "cached": format_bytes(snapshot.memory_cached),
            "buffers": format_bytes(snapshot.memory_buffers),
            "active": format_bytes(snapshot.memory_active),
            "inactive": format_bytes(snapshot.memory_inactive),
            "slab": format_bytes(snapshot.memory_slab),
            "shared": format_bytes(snapshot.memory_shared),
            "swap": f"{format_bytes(snapshot.swap_used)} / {format_bytes(snapshot.swap_total)}",
            "pressure": f"{snapshot.memory_pressure_percent:.2f}%",
            "total": format_bytes(snapshot.memory_total),
        })

        self._update_gpu_performance(snapshot)

        npu = self.perf_widgets["npu"]
        npu["value"].set_text(npu_text)
        npu["subtitle"].set_text(snapshot.npu_name or "No standard Linux NPU device")
        npu["meter"].set_value(None)
        self._set_provider_badge(
            npu["badge"], "DEVICE ONLY" if snapshot.npu_name else "UNAVAILABLE", "partial" if snapshot.npu_name else "unavailable"
        )
        npu["availability"].set_text(
            "NPU device detected / utilization provider unavailable"
            if snapshot.npu_name
            else "No standard Linux NPU provider detected"
        )
        npu["details"].update({
            "provider": snapshot.npu_name or "N/A",
            "state": "Detected; utilization unavailable" if snapshot.npu_name else "No provider detected",
        })

        self._update_disk_performance(snapshot)
        self._update_network_performance(snapshot)

        energy = self.perf_widgets["energy"]
        energy["value"].set_text(power_text)
        energy["subtitle"].set_text(snapshot.power_source)
        energy["meter"].set_value(self._adaptive_meter(snapshot.observed_power_watts, energy["graph"]))
        if snapshot.observed_power_watts is not None:
            energy["graph"].add(snapshot.observed_power_watts)
        energy_provider = snapshot.observed_power_watts is not None
        energy_badge = "SYSTEM POWER" if snapshot.power_watts is not None else "COMPONENT METERS"
        self._set_provider_badge(
            energy["badge"], energy_badge if energy_provider else "UNAVAILABLE",
            "available" if energy_provider else "unavailable",
        )
        energy["details"].update({
            "power": power_text,
            "source": snapshot.power_source,
            "cpu_power": f"{snapshot.cpu_package_watts:.1f} W" if snapshot.cpu_package_watts is not None else "N/A",
            "gpu_power": f"{snapshot.gpu_power_watts:.1f} W" if snapshot.gpu_power_watts is not None else "N/A",
            "system_power": f"{snapshot.power_watts:.1f} W" if snapshot.power_watts is not None else "N/A",
            "state": snapshot.battery_status,
            "charge": f"{snapshot.battery_percent:.0f}%" if snapshot.battery_percent is not None else "N/A",
            "processes": str(snapshot.process_count),
        })
        active_processes = sorted(snapshot.processes, key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)[:5]
        peak_cpu = max((process.cpu_percent for process in active_processes), default=0.0)
        for index, (label, progress) in enumerate(energy["impact_rows"]):
            if index < len(active_processes):
                process = active_processes[index]
                label.set_text(f"{process.name}  {process.cpu_percent:.1f}% CPU")
                progress.set_fraction(process.cpu_percent / peak_cpu if peak_cpu else 0.0)
            else:
                label.set_text("--")
                progress.set_fraction(0.0)

        thermals = self.perf_widgets["thermals"]
        thermals["value"].set_text(thermal_text)
        thermals["subtitle"].set_text(f"{snapshot.thermal_sensor_count} temperature sensors")
        thermals["meter"].set_value(observed_temperature)
        if observed_temperature is not None:
            thermals["graph"].add(observed_temperature)
        self._set_provider_badge(
            thermals["badge"], "TEMP SENSORS" if snapshot.thermal_sensors else "UNAVAILABLE",
            "available" if snapshot.thermal_sensors else "unavailable",
        )
        thermal_state = "Unavailable"
        if observed_temperature is not None:
            thermal_state = "Hot" if observed_temperature >= 90 else "Elevated" if observed_temperature >= 75 else "Normal"
        thermals["details"].update({
            "hotspot": thermal_text,
            "sensors": str(snapshot.thermal_sensor_count),
            "state": thermal_state,
        })
        self._update_thermal_sensor_tiles(snapshot)
        self._update_core_graphs(snapshot.per_cpu_percent, snapshot.cpu_core_types)

    def _record_io_histories(self, snapshot: SystemSnapshot) -> None:
        def append(resource: str, identifier: str, primary: float, first: float, second: float) -> None:
            history = self._io_histories[resource].setdefault(
                identifier,
                (deque(maxlen=60), deque(maxlen=60), deque(maxlen=60)),
            )
            history[0].append(max(0.0, primary))
            history[1].append(max(0.0, first))
            history[2].append(max(0.0, second))

        append(
            "disk",
            "combined",
            snapshot.disk_busy_percent,
            snapshot.disk_read_bps,
            snapshot.disk_write_bps,
        )
        for disk in snapshot.disks:
            append("disk", disk.identifier, disk.busy_percent, disk.read_bps, disk.write_bps)

        append(
            "network",
            "combined",
            snapshot.network_receive_bps + snapshot.network_send_bps,
            snapshot.network_receive_bps,
            snapshot.network_send_bps,
        )
        for interface in snapshot.network_interfaces:
            append(
                "network",
                interface.identifier,
                interface.receive_bps + interface.send_bps,
                interface.receive_bps,
                interface.send_bps,
            )

    def _sync_io_combo(
        self,
        resource: str,
        options: list[tuple[str, str]],
        default_identifier: str,
    ) -> str:
        widgets = self.perf_widgets[resource]
        combo = widgets["device_combo"]
        identifiers = [identifier for identifier, _label in options]
        cache_name = f"_{resource}_combo_identifiers"
        updating_name = f"_updating_{resource}_combo"
        if identifiers != getattr(self, cache_name, []):
            selected = combo.get_active_id()
            setattr(self, updating_name, True)
            combo.remove_all()
            for identifier, label in options:
                combo.append(identifier, label)
            target = selected if selected in identifiers else default_identifier
            if target not in identifiers and identifiers:
                target = identifiers[0]
            if identifiers:
                combo.set_active_id(target)
            setattr(self, updating_name, False)
            setattr(self, cache_name, identifiers)
        combo.set_sensitive(len(options) > 1)
        return combo.get_active_id() or default_identifier

    def _apply_io_history(self, resource: str, identifier: str) -> None:
        history = self._io_histories[resource].get(identifier)
        if history is None:
            history = (deque(maxlen=60), deque(maxlen=60), deque(maxlen=60))
        widgets = self.perf_widgets[resource]
        graph = widgets["graph"]
        graph.primary = history[0]
        graph.secondary.clear()
        graph.queue_draw()
        secondary = widgets["secondary_graph"]
        secondary.primary = history[1]
        secondary.secondary = history[2]
        secondary.queue_draw()

    def _io_selection_changed(self, _combo: Gtk.ComboBoxText, resource: str) -> None:
        if getattr(self, f"_updating_{resource}_combo", False) or not self.snapshot:
            return
        if resource == "disk":
            self._update_disk_performance(self.snapshot)
        else:
            self._update_network_performance(self.snapshot)

    def _update_disk_performance(self, snapshot: SystemSnapshot) -> None:
        widgets = self.perf_widgets["disk"]
        options = [("combined", f"All physical disks  /  {len(snapshot.disks)} devices")]
        options.extend(
            (
                disk.identifier,
                f"/dev/{disk.identifier}  /  {disk.model}  /  {disk.device_type}",
            )
            for disk in snapshot.disks
        )
        selected_id = self._sync_io_combo("disk", options, "combined")
        selected = next((disk for disk in snapshot.disks if disk.identifier == selected_id), None)
        if selected is None:
            busy = snapshot.disk_busy_percent
            read_bps = snapshot.disk_read_bps
            write_bps = snapshot.disk_write_bps
            read_total = snapshot.disk_read_total
            write_total = snapshot.disk_write_total
            capacity = snapshot.disk_capacity
            used: int | None = snapshot.disk_used
            free: int | None = snapshot.disk_free
            selection = "All physical disks"
            device_type = "Combined"
            subtitle = f"{snapshot.disk_device_count} physical devices / combined"
            selected_id = "combined"
        else:
            busy = selected.busy_percent
            read_bps = selected.read_bps
            write_bps = selected.write_bps
            read_total = selected.read_total
            write_total = selected.write_total
            capacity = selected.capacity
            used = selected.used
            free = selected.free
            selection = f"/dev/{selected.identifier}  /  {selected.model}"
            device_type = selected.device_type
            subtitle = f"{selected.model}  •  {selected.device_type}  •  {format_bytes(selected.capacity)}"

        widgets["value"].set_text(f"{busy:.1f}%")
        widgets["subtitle"].set_text(subtitle)
        widgets["meter"].set_value(busy)
        self._apply_io_history("disk", selected_id)
        widgets["details"].update({
            "selection": selection,
            "type": device_type,
            "devices": str(snapshot.disk_device_count),
            "active": f"{busy:.1f}%",
            "read": format_bytes(read_bps, rate=True),
            "write": format_bytes(write_bps, rate=True),
            "read_total": format_bytes(read_total),
            "write_total": format_bytes(write_total),
            "capacity": format_bytes(capacity),
            "used": format_bytes(used) if used is not None else "N/A",
            "free": format_bytes(free) if free is not None else "N/A",
        })

    def _update_network_performance(self, snapshot: SystemSnapshot) -> None:
        widgets = self.perf_widgets["network"]
        options = [("combined", f"All interfaces  /  {len(snapshot.network_interfaces)} detected")]
        options.extend(
            (
                interface.identifier,
                f"{interface.identifier}  /  {interface.connection_type}  /  {interface.state}",
            )
            for interface in snapshot.network_interfaces
        )
        default_id = next(
            (interface.identifier for interface in snapshot.network_interfaces if interface.primary),
            "combined",
        )
        selected_id = self._sync_io_combo("network", options, default_id)
        selected = next(
            (interface for interface in snapshot.network_interfaces if interface.identifier == selected_id),
            None,
        )
        if selected is None:
            receive_bps = snapshot.network_receive_bps
            send_bps = snapshot.network_send_bps
            receive_total = snapshot.network_receive_total
            send_total = snapshot.network_send_total
            link_speed = None
            interface_name = "All interfaces"
            connection_type = "Combined"
            active_count = sum(
                interface.state in ("Up", "Unknown") for interface in snapshot.network_interfaces
            )
            state = f"{active_count} active / {snapshot.network_interface_count} detected"
            hardware = ipv4 = ipv6 = "Multiple / select an interface"
            mtu = None
            subtitle = f"{snapshot.network_interface_count} interfaces / combined"
            selected_id = "combined"
        else:
            receive_bps = selected.receive_bps
            send_bps = selected.send_bps
            receive_total = selected.receive_total
            send_total = selected.send_total
            link_speed = selected.link_speed_mbps
            interface_name = selected.identifier
            connection_type = selected.connection_type
            state = selected.state
            hardware = selected.hardware_address
            ipv4 = selected.ipv4_addresses
            ipv6 = selected.ipv6_addresses
            mtu = selected.mtu
            primary_text = "  •  default route" if selected.primary else ""
            subtitle = f"{selected.identifier}  •  {selected.connection_type}{primary_text}"

        rate = receive_bps + send_bps
        widgets["value"].set_text(format_bytes(rate, rate=True))
        widgets["subtitle"].set_text(subtitle)
        self._apply_io_history("network", selected_id)
        if link_speed:
            capacity = link_speed * 1_000_000.0 / 8.0
            meter_value = min(100.0, 100.0 * rate / capacity)
        else:
            meter_value = self._adaptive_meter(rate, widgets["graph"])
        widgets["meter"].set_value(meter_value)
        widgets["details"].update({
            "interface": interface_name,
            "interfaces": str(snapshot.network_interface_count),
            "type": connection_type,
            "state": state,
            "link": f"{link_speed:,} Mbps" if link_speed else "N/A / per interface",
            "receive": format_bytes(receive_bps, rate=True),
            "send": format_bytes(send_bps, rate=True),
            "received_total": format_bytes(receive_total),
            "sent_total": format_bytes(send_total),
            "hardware": hardware,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "mtu": f"{mtu:,} bytes" if mtu is not None else "N/A",
        })

    def _gpu_selection_changed(self, _combo: Gtk.ComboBoxText) -> None:
        if getattr(self, "_updating_gpu_combo", False) or not self.snapshot:
            return
        self.perf_widgets["gpu"]["graph"].clear()
        self._update_gpu_performance(self.snapshot)

    def _update_gpu_performance(self, snapshot: SystemSnapshot) -> None:
        widgets = self.perf_widgets["gpu"]
        combo = widgets["device_combo"]
        identifiers = [gpu.identifier for gpu in snapshot.gpus]
        if identifiers != getattr(self, "_gpu_combo_identifiers", []):
            selected_id = combo.get_active_id()
            self._updating_gpu_combo = True
            combo.remove_all()
            for index, adapter in enumerate(snapshot.gpus):
                combo.append(adapter.identifier, f"GPU {index}  /  {adapter.name}")
            if identifiers:
                combo.set_active_id(selected_id if selected_id in identifiers else identifiers[0])
            self._updating_gpu_combo = False
            self._gpu_combo_identifiers = identifiers
            widgets["graph"].clear()
        combo.set_sensitive(bool(snapshot.gpus))

        selected_id = combo.get_active_id()
        adapter = next((item for item in snapshot.gpus if item.identifier == selected_id), None)
        if adapter is None:
            widgets["value"].set_text("N/A")
            widgets["subtitle"].set_text("No graphics adapter detected")
            widgets["meter"].set_value(None)
            self._set_provider_badge(widgets["badge"], "UNAVAILABLE", "unavailable")
            widgets["details"].update({key: "N/A" for key in widgets["details"].value_labels})
            return

        usage_text = f"{adapter.utilization:.1f}%" if adapter.utilization is not None else "N/A"
        widgets["value"].set_text(usage_text)
        widgets["subtitle"].set_text(f"{adapter.name}  •  {adapter.driver}")
        widgets["meter"].set_value(adapter.utilization)
        if adapter.utilization is not None:
            widgets["graph"].add(adapter.utilization)
        partial = "accessible clients" in adapter.utilization_source
        nvidia = adapter.utilization_source.startswith("nvidia-smi")
        badge_text = "NVIDIA-SMI" if nvidia else "VISIBLE CLIENTS" if partial else "NATIVE PROVIDER"
        badge_state = "available" if adapter.utilization is not None and not partial else "partial"
        self._set_provider_badge(widgets["badge"], badge_text, badge_state)
        widgets["details"].update({
            "adapter": adapter.name,
            "driver": adapter.driver,
            "pci": adapter.pci_address,
            "device_id": adapter.pci_id,
            "usage": usage_text,
            "source": adapter.utilization_source,
            "frequency": f"{adapter.frequency_mhz:.0f} MHz" if adapter.frequency_mhz is not None else "N/A",
            "max_frequency": f"{adapter.frequency_max_mhz:.0f} MHz" if adapter.frequency_max_mhz is not None else "N/A",
            "memory_mode": adapter.memory_mode,
            "vram_used": format_bytes(adapter.memory_used) if adapter.memory_used is not None else "N/A",
            "vram_total": format_bytes(adapter.memory_total) if adapter.memory_total is not None else "N/A",
            "render": adapter.device_nodes,
            "temperature": f"{adapter.temperature_c:.0f} C" if adapter.temperature_c is not None else "N/A",
            "power": f"{adapter.power_watts:.1f} W" if adapter.power_watts is not None else "N/A",
            "fan": f"{adapter.fan_percent:.0f}%" if adapter.fan_percent is not None else "N/A",
        })

    @staticmethod
    def _set_provider_badge(label: Gtk.Label, text: str, state: str) -> None:
        context = label.get_style_context()
        for css_class in ("partial-provider", "unavailable-provider"):
            context.remove_class(css_class)
        if state in ("partial", "unavailable"):
            context.add_class(f"{state}-provider")
        label.set_text(text)

    @staticmethod
    def _adaptive_meter(value: float | None, graph: HistoryGraph) -> float | None:
        if value is None:
            return None
        maximum = max(value, max(graph.primary, default=0.0))
        return 100.0 * value / maximum if maximum else 0.0

    def _network_utilization(
        self, snapshot: SystemSnapshot, rate: float, graph: HistoryGraph | None = None
    ) -> float:
        if snapshot.link_speed_mbps:
            capacity = snapshot.link_speed_mbps * 1_000_000.0 / 8.0
            return min(100.0, 100.0 * rate / capacity)
        return self._adaptive_meter(rate, graph) if graph is not None else 0.0

    def _update_core_graphs(self, values: list[float], core_types: list[str]) -> None:
        normalized_types = [core_types[index] if index < len(core_types) else "" for index in range(len(values))]
        if len(values) != len(self.core_graphs) or normalized_types != self._core_graph_types:
            if self._core_grid_layout_source is not None:
                GLib.source_remove(self._core_grid_layout_source)
                self._core_grid_layout_source = None
            self._pending_core_grid_layout = None
            for child in self.core_grid.get_children():
                self.core_grid.remove(child)
            self.core_graphs = []
            for index, _value in enumerate(values):
                graph = CoreGraph(index, normalized_types[index])
                self.core_graphs.append(graph)
            self._core_graph_types = normalized_types
            self._core_grid_density = None
            self._core_grid_columns = None
            if not self.core_graphs:
                self.core_grid.set_size_request(-1, -1)
            self._layout_core_grid()
        for graph, value in zip(self.core_graphs, values):
            graph.add(value)

    def _on_core_grid_size_allocate(self, _widget: Gtk.Widget, allocation: Gdk.Rectangle) -> None:
        self._layout_core_grid(allocation.width)

    def _on_cpu_section_toggled(self, _button: Gtk.Button) -> None:
        if self._cpu_section_persistence_enabled:
            save_cpu_section_preferences(
                self.cpu_overall_section.section_expanded,
                self.cpu_logical_section.section_expanded,
            )
        GLib.idle_add(self._relayout_core_grid_after_section_toggle)

    def _relayout_core_grid_after_section_toggle(self) -> bool:
        if self._core_grid_layout_source is not None:
            GLib.source_remove(self._core_grid_layout_source)
            self._core_grid_layout_source = None
        self._pending_core_grid_layout = None
        self._core_grid_density = None
        self._core_grid_columns = None
        self._layout_core_grid()
        self.core_grid.queue_resize()
        self.cpu_logical_section.queue_resize()
        return GLib.SOURCE_REMOVE

    def _layout_core_grid(self, available_width: int | None = None) -> None:
        core_count = len(self.core_graphs)
        if not core_count:
            return
        width = available_width or self.core_grid.get_allocated_width()
        if width <= 1:
            return

        gap = CORE_GRID_SPACING
        window_height = self.get_allocated_height()
        if window_height <= 1:
            window_height = 720
        target_height = max(220, min(380, int(window_height * 0.42)))
        layouts = []
        if not self.cpu_overall_section.section_expanded:
            layouts.append(("expanded", *CORE_GRAPH_SIZES["expanded"], 8))
        layouts.extend((
            ("full", 108, 70, 8),
            ("compact", 82, 54, 12),
            ("numeric", 62, 34, 16),
        ))

        selected_layout = layouts[-1]
        selected_columns = 1
        for layout in layouts:
            density, tile_width, tile_height, max_columns = layout
            capacity = max(1, min(max_columns, core_count, (width + gap) // (tile_width + gap)))
            row_count = math.ceil(core_count / capacity)
            aligned_columns = [
                columns
                for columns in range(capacity, 0, -1)
                if math.ceil(core_count / columns) == row_count and core_count % columns == 0
            ]
            columns = aligned_columns[0] if aligned_columns else capacity
            row_count = math.ceil(core_count / columns)
            grid_height = (
                row_count * tile_height
                + max(0, row_count - 1) * gap
                + CORE_GRID_BOTTOM_GUARD
            )
            selected_layout = layout
            selected_columns = columns
            if grid_height <= target_height:
                break

        layout = (selected_layout[0], selected_columns)
        if layout == self._pending_core_grid_layout:
            return
        if layout == (self._core_grid_density, self._core_grid_columns):
            return
        self._pending_core_grid_layout = layout
        if self._core_grid_layout_source is None:
            self._core_grid_layout_source = GLib.idle_add(self._apply_core_grid_layout)

    def _apply_core_grid_layout(self) -> bool:
        pending_layout = self._pending_core_grid_layout
        self._pending_core_grid_layout = None
        self._core_grid_layout_source = None
        if pending_layout is None:
            return GLib.SOURCE_REMOVE
        density, columns = pending_layout
        for child in self.core_grid.get_children():
            self.core_grid.remove(child)
        for index, graph in enumerate(self.core_graphs):
            graph.set_density(density)
            self.core_grid.attach(graph, index % columns, index // columns, 1, 1)
        tile_height = CORE_GRAPH_SIZES[density][1]
        row_count = math.ceil(len(self.core_graphs) / columns)
        required_height = (
            row_count * tile_height
            + max(0, row_count - 1) * self.core_grid.get_row_spacing()
            + CORE_GRID_BOTTOM_GUARD
        )
        self.core_grid.set_size_request(-1, required_height)
        self._core_grid_density = density
        self._core_grid_columns = columns
        self.core_grid.show_all()
        self.core_grid.queue_resize()
        self.cpu_logical_section.queue_resize()
        return GLib.SOURCE_REMOVE

    def _update_thermal_sensor_tiles(self, snapshot: SystemSnapshot) -> None:
        sensor_order = [sensor.identifier for sensor in snapshot.thermal_sensors]
        if sensor_order != getattr(self, "_thermal_sensor_order", []):
            for child in self.thermal_sensor_flow.get_children():
                self.thermal_sensor_flow.remove(child)
            self.thermal_sensor_tiles = {}
            for sensor in snapshot.thermal_sensors:
                tile = ThermalSensorTile(sensor.identifier, sensor.label, sensor.source)
                self.thermal_sensor_flow.add(tile)
                self.thermal_sensor_tiles[sensor.identifier] = tile
            self._thermal_sensor_order = sensor_order
            self.thermal_sensor_flow.show_all()
        for sensor in snapshot.thermal_sensors:
            tile = self.thermal_sensor_tiles.get(sensor.identifier)
            if tile:
                tile.update(sensor.temperature_c)

    def _desktop_app_for_id(self, application_id: str) -> Gio.AppInfo | None:
        normalized = application_id.removesuffix(".desktop").casefold()
        direct = self._desktop_apps_by_id.get(normalized)
        if direct is not None:
            return direct
        return next(
            (
                app_info
                for candidate, app_info in self._desktop_apps_by_id.items()
                if candidate.endswith(f".{normalized}") or normalized.endswith(f".{candidate}")
            ),
            None,
        )

    def _desktop_app_for_process(self, process: ProcessInfo) -> Gio.AppInfo | None:
        candidates = [process.name]
        try:
            command = shlex.split(process.command)
        except ValueError:
            command = process.command.split()
        if command:
            executable = Path(command[0]).name
            if executable not in {"env", "flatpak", "bwrap", "python", "python3", "sh", "bash"}:
                candidates.append(executable)
        for candidate in candidates:
            app_info = self._desktop_apps_by_executable.get(Path(candidate).name.casefold())
            if app_info is not None:
                return app_info
        return None

    @staticmethod
    def _application_fallback_name(application_id: str) -> str:
        name = application_id.rsplit(".", 1)[-1].replace("-", " ").replace("_", " ").strip()
        return name or application_id

    @staticmethod
    def _application_icon_name(app_info: Gio.AppInfo | None) -> str:
        icon = app_info.get_icon() if app_info is not None else None
        if isinstance(icon, Gio.ThemedIcon):
            names = icon.get_names()
            if names:
                return names[0]
        return "application-x-executable-symbolic"

    def _explicit_application_identity(self, process: ProcessInfo) -> tuple[str, str, str] | None:
        application_id = application_id_from_control_group(process.control_group)
        app_info = self._desktop_app_for_id(application_id) if application_id else None
        if app_info is None:
            app_info = self._desktop_app_for_process(process)
        if app_info is not None:
            app_id = (app_info.get_id() or application_id or process.name).removesuffix(".desktop")
            return f"desktop:{app_id.casefold()}", app_info.get_display_name(), self._application_icon_name(app_info)
        if application_id:
            return (
                f"scope:{application_id.casefold()}",
                self._application_fallback_name(application_id),
                "application-x-executable-symbolic",
            )
        return None

    def _application_groups(self, processes: list[ProcessInfo]) -> list[ApplicationGroup]:
        eligible = {
            process.pid: process
            for process in processes
            if process.user == self._current_user and not process.command.startswith("[")
        }
        infrastructure = {
            "systemd",
            "dbus-daemon",
            "dbus-broker",
            "gnome-session-binary",
            "gnome-session-c",
            "xdg-permission-store",
        }
        identities = {pid: self._explicit_application_identity(process) for pid, process in eligible.items()}
        grouped: dict[str, ApplicationGroup] = {}

        for process in eligible.values():
            chain: list[ProcessInfo] = []
            visited: set[int] = set()
            current = process
            while current.pid not in visited:
                visited.add(current.pid)
                chain.append(current)
                parent = eligible.get(current.ppid)
                if parent is None or parent.pid == current.pid:
                    break
                current = parent

            identity = next((identities[item.pid] for item in chain if identities[item.pid] is not None), None)
            root = chain[-1]
            if identity is None:
                if any(service_membership_from_control_group(item.control_group) for item in chain):
                    continue
                if root.name.casefold() in infrastructure:
                    continue
                identity = (
                    f"process:{root.pid}",
                    root.name,
                    "application-x-executable-symbolic",
                )

            identifier, name, icon_name = identity
            group = grouped.setdefault(identifier, ApplicationGroup(identifier, name, icon_name, []))
            group.processes.append(process)

        return sorted(
            grouped.values(),
            key=lambda group: (
                sum(process.cpu_percent for process in group.processes),
                sum(process.memory_bytes for process in group.processes),
                group.name.casefold(),
            ),
            reverse=True,
        )

    @staticmethod
    def _process_tree(processes: list[ProcessInfo]) -> tuple[list[ProcessInfo], dict[int, list[ProcessInfo]]]:
        by_pid = {process.pid: process for process in processes}
        children: dict[int, list[ProcessInfo]] = defaultdict(list)
        roots: list[ProcessInfo] = []
        for process in processes:
            if process.ppid in by_pid and process.ppid != process.pid:
                children[process.ppid].append(process)
            else:
                roots.append(process)
        roots.sort(key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)
        for items in children.values():
            items.sort(key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)
        return roots, children

    @staticmethod
    def _compare_tree_rows(
        model: Gtk.TreeModel,
        left: Gtk.TreeIter,
        right: Gtk.TreeIter,
        column: int,
    ) -> int:
        left_value = model.get_value(left, column)
        right_value = model.get_value(right, column)
        if column == 1:
            left_value = int(left_value) if str(left_value).isdigit() else -1
            right_value = int(right_value) if str(right_value).isdigit() else -1
        elif isinstance(left_value, str) and isinstance(right_value, str):
            left_value = left_value.casefold()
            right_value = right_value.casefold()
        return (left_value > right_value) - (left_value < right_value)

    @classmethod
    def _compare_service_tree_rows(
        cls,
        model: Gtk.TreeModel,
        left: Gtk.TreeIter,
        right: Gtk.TreeIter,
        column: int,
    ) -> int:
        left_key = model.get_value(left, 9)
        right_key = model.get_value(right, 9)
        if left_key.startswith("scope:") and right_key.startswith("scope:"):
            scope_order = {"scope:user": 0, "scope:system": 1}
            result = (scope_order[left_key] > scope_order[right_key]) - (
                scope_order[left_key] < scope_order[right_key]
            )
            _sort_column, sort_order = model.get_sort_column_id()
            return -result if sort_order == Gtk.SortType.DESCENDING else result
        return cls._compare_tree_rows(model, left, right, column)

    @staticmethod
    def _tree_paths_by_key(model: Gtk.TreeModel, key_column: int) -> dict[str, Gtk.TreePath]:
        paths: dict[str, Gtk.TreePath] = {}

        def remember_path(
            tree_model: Gtk.TreeModel,
            path: Gtk.TreePath,
            tree_iter: Gtk.TreeIter,
            _data=None,
        ) -> bool:
            paths[tree_model.get_value(tree_iter, key_column)] = path.copy()
            return False

        model.foreach(remember_path, None)
        return paths

    def _expanded_application_keys(self) -> set[str]:
        expanded: set[str] = set()

        def remember(view: Gtk.TreeView, path: Gtk.TreePath, _data=None) -> None:
            tree_iter = view.get_model().get_iter(path)
            expanded.add(view.get_model().get_value(tree_iter, 11))

        self.application_view.map_expanded_rows(remember, None)
        return expanded

    def _render_applications(self, processes: list[ProcessInfo]) -> None:
        selected_model, selected_iter = self.application_view.get_selection().get_selected()
        selected_key = selected_model.get_value(selected_iter, 11) if selected_iter is not None else None
        expanded_keys = self._expanded_application_keys()
        adjustment = self.application_scroller.get_vadjustment()
        previous_scroll = adjustment.get_value()
        query = self.application_search.get_text().strip().casefold()
        groups = self._application_groups(processes)
        self.application_store.clear()
        visible_processes = 0

        for group in groups:
            searchable = " ".join(
                [group.name, group.identifier]
                + [f"{process.pid} {process.name} {process.command}" for process in group.processes]
            ).casefold()
            if query and query not in searchable:
                continue
            visible_processes += len(group.processes)
            cpu = sum(process.cpu_percent for process in group.processes)
            memory = sum(process.memory_bytes for process in group.processes)
            swap = sum(process.swap_bytes for process in group.processes)
            threads = sum(process.threads for process in group.processes)
            read_bytes = sum(process.read_bytes for process in group.processes)
            write_bytes = sum(process.write_bytes for process in group.processes)
            group_key = f"application:{group.identifier}"
            group_iter = self.application_store.append(
                None,
                (
                    group.name,
                    "",
                    cpu,
                    memory,
                    swap,
                    threads,
                    read_bytes,
                    write_bytes,
                    group.icon_name,
                    None,
                    group,
                    group_key,
                ),
            )
            roots, children = self._process_tree(group.processes)
            visited: set[int] = set()

            def append_process(process: ProcessInfo, parent: Gtk.TreeIter) -> None:
                if process.pid in visited:
                    return
                visited.add(process.pid)
                process_key = f"process:{process.pid}"
                process_iter = self.application_store.append(
                    parent,
                    (
                        process.name,
                        str(process.pid),
                        process.cpu_percent,
                        process.memory_bytes,
                        process.swap_bytes,
                        process.threads,
                        process.read_bytes,
                        process.write_bytes,
                        "system-run-symbolic",
                        process,
                        group,
                        process_key,
                    ),
                )
                for child in children.get(process.pid, []):
                    append_process(child, process_iter)

            for root in roots:
                append_process(root, group_iter)
            for process in group.processes:
                append_process(process, group_iter)

        paths = self._tree_paths_by_key(self.application_store, 11)
        expanded_paths = sorted(
            (paths[key] for key in expanded_keys if key in paths),
            key=lambda path: path.get_depth(),
        )
        for path in expanded_paths:
            self.application_view.expand_row(path, False)
        selected_path = paths.get(selected_key)
        if selected_path is not None:
            self.application_view.get_selection().select_path(selected_path)
        GLib.idle_add(self._restore_application_scroll, previous_scroll)
        visible_groups = self.application_store.iter_n_children(None)
        self.application_count_label.set_text(f"{visible_groups} applications  /  {visible_processes} processes")
        self.application_status.set_text(
            f"CURRENT USER {self._current_user}  /  DESKTOP + CGROUP + ANCESTRY GROUPING  /  "
            f"SAMPLE {datetime.now().strftime('%H:%M:%S')}"
        )
        self._application_selection_changed(self.application_view.get_selection())
        self._last_application_render = time.monotonic()

    def _restore_application_scroll(self, value: float) -> bool:
        adjustment = self.application_scroller.get_vadjustment()
        adjustment.set_value(
            clamped_scroll_value(value, adjustment.get_lower(), adjustment.get_upper(), adjustment.get_page_size())
        )
        return GLib.SOURCE_REMOVE

    def _selected_application_target(self) -> tuple[ApplicationGroup | None, ProcessInfo | None]:
        model, tree_iter = self.application_view.get_selection().get_selected()
        if tree_iter is None:
            return None, None
        return model.get_value(tree_iter, 10), model.get_value(tree_iter, 9)

    def _application_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        group, process = self._selected_application_target()
        targets = [process] if process is not None else group.processes if group is not None else []
        stopped = [target.state in ("Stopped", "Tracing") for target in targets]
        self.application_pause_button.set_sensitive(any(not state for state in stopped))
        self.application_resume_button.set_sensitive(any(stopped))
        self.application_end_button.set_sensitive(bool(targets))
        self.application_kill_button.set_sensitive(bool(targets))

    def _application_row_activated(
        self,
        view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn | None,
    ) -> None:
        model = view.get_model()
        tree_iter = model.get_iter(path)
        process = model.get_value(tree_iter, 9)
        if process is not None:
            self._open_process_details(process)
        elif view.row_expanded(path):
            view.collapse_row(path)
        else:
            view.expand_row(path, False)

    def _on_application_button_press(self, view: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button != Gdk.BUTTON_SECONDARY or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        target = view.get_path_at_pos(int(event.x), int(event.y))
        if target is None:
            return False
        path, _column, _cell_x, _cell_y = target
        view.grab_focus()
        view.get_selection().select_path(path)
        return self._popup_application_menu(event)

    def _on_application_popup_menu(self, _view: Gtk.TreeView) -> bool:
        return self._popup_application_menu()

    def _popup_application_menu(self, event: Gdk.EventButton | None = None) -> bool:
        group, process = self._selected_application_target()
        if process is not None:
            menu = self._build_process_menu(process)
        elif group is not None:
            menu = self._build_application_menu(group)
        else:
            return False
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(self.application_view, Gdk.Gravity.CENTER, Gdk.Gravity.CENTER, None)
        return True

    def _build_application_menu(self, group: ApplicationGroup) -> Gtk.Menu:
        menu = Gtk.Menu()
        for label, callback in (
            ("End application", lambda: self._confirm_application_action(False, group=group)),
            ("Force stop application", lambda: self._confirm_application_action(True, group=group)),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, action=callback: action())
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        pause_item = Gtk.MenuItem(label="Pause application")
        pause_item.connect("activate", lambda _item: self._control_application_target("pause", group=group))
        menu.append(pause_item)
        resume_item = Gtk.MenuItem(label="Resume application")
        resume_item.connect("activate", lambda _item: self._control_application_target("resume", group=group))
        menu.append(resume_item)
        menu.append(self._build_signal_submenu(lambda name: self._signal_application_target(name, group=group)))
        menu.append(Gtk.SeparatorMenuItem())
        details_item = Gtk.MenuItem(label="Details")
        details_item.connect("activate", lambda _item: self._open_application_details(group))
        menu.append(details_item)
        menu.show_all()
        self._application_context_menu = menu
        return menu

    def _application_target_processes(
        self,
        group: ApplicationGroup | None = None,
        process: ProcessInfo | None = None,
    ) -> list[ProcessInfo]:
        if group is None and process is None:
            group, process = self._selected_application_target()
        return [process] if process is not None else list(group.processes) if group is not None else []

    def _confirm_application_action(
        self,
        force: bool,
        *,
        group: ApplicationGroup | None = None,
        process: ProcessInfo | None = None,
    ) -> None:
        targets = self._application_target_processes(group, process)
        if not targets:
            self._message("Select an application or process", "Choose a row before using this action.")
            return
        target_name = process.name if process is not None else group.name if group is not None else "selection"
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=f"{'Force stop' if force else 'End'} {target_name}?",
        )
        dialog.format_secondary_text(
            f"This action targets {len(targets)} process{'es' if len(targets) != 1 else ''}. "
            + ("Unsaved work may be lost immediately." if force else "Processes receive SIGTERM and may save their state.")
        )
        dialog.add_button("Force stop" if force else "End", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._signal_process_targets(targets, "KILL" if force else "TERM")

    def _control_application_target(
        self,
        action: str,
        *,
        group: ApplicationGroup | None = None,
        process: ProcessInfo | None = None,
    ) -> None:
        targets = self._application_target_processes(group, process)
        if not targets:
            self._message("Select an application or process", "Choose a row before using this action.")
            return
        errors: list[str] = []
        for target in targets:
            try:
                if action == "pause":
                    self.collector.suspend_process(target.pid)
                elif action == "resume":
                    self.collector.resume_process(target.pid)
                else:
                    raise ValueError(f"Unsupported process action: {action}")
            except (PermissionError, ProcessLookupError, OSError, ValueError) as error:
                errors.append(f"PID {target.pid}: {error}")
        if errors:
            self._message("Some process actions failed", "\n".join(errors[:8]), Gtk.MessageType.ERROR)
        self.request_update()

    def _signal_application_target(
        self,
        signal_name: str,
        *,
        group: ApplicationGroup | None = None,
        process: ProcessInfo | None = None,
    ) -> None:
        targets = self._application_target_processes(group, process)
        if targets:
            target_name = process.name if process is not None else group.name if group is not None else "selection"
            self._send_signal_with_confirmation(targets, signal_name, target_name)

    def _send_signal_with_confirmation(
        self,
        targets: list[ProcessInfo],
        signal_name: str,
        target_name: str,
    ) -> None:
        if signal_name in {"TERM", "KILL"}:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.CANCEL,
                text=f"Send {signal_name} to {target_name}?",
            )
            dialog.format_secondary_text(
                f"The signal targets {len(targets)} process{'es' if len(targets) != 1 else ''}. "
                + ("Unsaved work may be lost immediately." if signal_name == "KILL" else "Processes may terminate.")
            )
            dialog.add_button(f"Send {signal_name}", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
        self._signal_process_targets(targets, signal_name)

    def _signal_process_targets(self, targets: list[ProcessInfo], signal_name: str) -> None:
        errors: list[str] = []
        for target in sorted(targets, key=lambda item: item.pid, reverse=True):
            try:
                self.collector.send_process_signal(target.pid, signal_name)
            except (PermissionError, ProcessLookupError, OSError, ValueError) as error:
                errors.append(f"PID {target.pid}: {error}")
        if errors:
            self._message("Some signals failed", "\n".join(errors[:8]), Gtk.MessageType.ERROR)
        self.request_update()

    def _open_application_details(self, group: ApplicationGroup) -> None:
        dialog = Gtk.Dialog(title=group.name, transient_for=self, modal=True)
        dialog.get_style_context().add_class("process-details-dialog")
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(650, 470)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(16)
        details = DetailGrid(
            [
                ("identifier", "Application identity"), ("processes", "Processes"),
                ("cpu", "Combined CPU"), ("memory", "Resident memory"),
                ("swap", "Swap"), ("threads", "Threads"),
                ("read", "Total read I/O"), ("write", "Total write I/O"),
            ],
            columns=2,
        )
        details.update({
            "identifier": group.identifier,
            "processes": str(len(group.processes)),
            "cpu": f"{sum(process.cpu_percent for process in group.processes):.1f}%",
            "memory": format_bytes(sum(process.memory_bytes for process in group.processes)),
            "swap": format_bytes(sum(process.swap_bytes for process in group.processes)),
            "threads": str(sum(process.threads for process in group.processes)),
            "read": format_bytes(sum(process.read_bytes for process in group.processes)),
            "write": format_bytes(sum(process.write_bytes for process in group.processes)),
        })
        body.pack_start(details, False, False, 0)
        process_list = Gtk.Label(
            label="\n".join(f"{process.pid:<8} {process.name}  {process.command}" for process in group.processes),
            xalign=0,
        )
        process_list.set_selectable(True)
        process_list.set_line_wrap(True)
        body.pack_start(scrollable(process_list), True, True, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _process_visible(self, model: Gtk.TreeModel, tree_iter: Gtk.TreeIter, _data=None) -> bool:
        if not hasattr(self, "process_search"):
            return True
        query = self.process_search.get_text().strip().casefold()
        if not query:
            return True
        searchable = " ".join(str(model.get_value(tree_iter, index)) for index in (0, 1, 2, 3, 10)).casefold()
        return query in searchable

    def _process_view_changed(self, _combo: Gtk.ComboBoxText) -> None:
        tree_mode = (self.process_view_combo.get_active_id() or "all") == "tree"
        self._changing_process_sort = True
        try:
            for column in self.process_view.get_columns():
                column.set_clickable(not tree_mode)
            if tree_mode:
                self.process_sort.set_sort_column_id(
                    12,
                    Gtk.SortType.ASCENDING,
                )
            else:
                self.process_sort.set_sort_column_id(*self._process_sort_preference)
        finally:
            self._changing_process_sort = False
        if self.snapshot:
            self._reset_process_scroll = True
            self._render_processes(self.snapshot.processes)

    def _process_sort_changed(self, model: Gtk.TreeModelSort) -> None:
        if self._changing_process_sort:
            return
        sort_column, sort_order = model.get_sort_column_id()
        if sort_column >= 0:
            self._process_sort_preference = (sort_column, sort_order)

    def _selected_process(self) -> ProcessInfo | None:
        model, tree_iter = self.process_view.get_selection().get_selected()
        return model.get_value(tree_iter, 11) if tree_iter is not None else None

    def _ordered_processes(self, processes: list[ProcessInfo]) -> list[tuple[ProcessInfo, int]]:
        mode = self.process_view_combo.get_active_id() or "all"
        filtered = processes
        if mode == "mine":
            filtered = [process for process in processes if process.user == self._current_user]
        elif mode == "active":
            filtered = [process for process in processes if process.state == "Running" or process.cpu_percent >= 0.1]
        if mode != "tree":
            return [(process, 0) for process in sorted(filtered, key=lambda item: item.cpu_percent, reverse=True)]

        by_pid = {process.pid: process for process in filtered}
        children: dict[int, list[ProcessInfo]] = defaultdict(list)
        roots: list[ProcessInfo] = []
        for process in filtered:
            if process.ppid in by_pid and process.ppid != process.pid:
                children[process.ppid].append(process)
            else:
                roots.append(process)
        for group in children.values():
            group.sort(key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)
        roots.sort(key=lambda item: (item.cpu_percent, item.memory_bytes), reverse=True)
        ordered: list[tuple[ProcessInfo, int]] = []
        visited: set[int] = set()

        def visit(process: ProcessInfo, depth: int) -> None:
            if process.pid in visited:
                return
            visited.add(process.pid)
            ordered.append((process, min(depth, 12)))
            for child in children.get(process.pid, []):
                visit(child, depth + 1)

        for root in roots:
            visit(root, 0)
        for process in filtered:
            visit(process, 0)
        return ordered

    def _render_processes(self, processes: list[ProcessInfo]) -> None:
        selected = self._selected_process() if self.follow_selection.get_active() else None
        selected_pid = selected.pid if selected else None
        adjustment = self.process_scroller.get_vadjustment()
        previous_scroll = adjustment.get_value()
        self.process_store.clear()
        selected_path = None
        rows = self._ordered_processes(processes)
        tree_mode = (self.process_view_combo.get_active_id() or "all") == "tree"
        for sequence, (process, depth) in enumerate(rows):
            tree_iter = self.process_store.append(
                (
                    process.pid,
                    f"{'  ' * depth}{process.name}" if tree_mode else process.name,
                    process.user,
                    process.state,
                    process.cpu_percent,
                    process.memory_bytes,
                    process.threads,
                    process.read_bytes,
                    process.write_bytes,
                    datetime.fromtimestamp(process.started_at).strftime("%Y-%m-%d %H:%M"),
                    process.command,
                    process,
                    sequence,
                )
            )
            if process.pid == selected_pid:
                selected_path = self.process_store.get_path(tree_iter)
        self.process_filter.refilter()
        self.process_count_label.set_text(f"{len(rows)} / {len(processes)} processes")
        running = sum(process.state == "Running" for process in processes)
        resident = sum(process.memory_bytes for process in processes)
        self.process_status.set_text(
            f"RUNNING {running}  /  THREADS {sum(process.threads for process in processes):,}  /  "
            f"RESIDENT {format_bytes(resident)}  /  SAMPLE {datetime.now().strftime('%H:%M:%S')}"
        )
        if selected_path is not None:
            filtered_path = self.process_filter.convert_child_path_to_path(selected_path)
            if filtered_path:
                sorted_path = self.process_sort.convert_child_path_to_path(filtered_path)
                if sorted_path:
                    self.process_view.get_selection().select_path(sorted_path)
        if getattr(self, "_reset_process_scroll", False):
            GLib.idle_add(self._scroll_process_view_to_top)
        else:
            GLib.idle_add(self._restore_process_scroll, previous_scroll)
        self._reset_process_scroll = False
        self._last_process_render = time.monotonic()

    def _scroll_process_view_to_top(self) -> bool:
        adjustment = self.process_scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())
        return GLib.SOURCE_REMOVE

    def _restore_process_scroll(self, value: float) -> bool:
        adjustment = self.process_scroller.get_vadjustment()
        adjustment.set_value(
            clamped_scroll_value(
                value,
                adjustment.get_lower(),
                adjustment.get_upper(),
                adjustment.get_page_size(),
            )
        )
        return GLib.SOURCE_REMOVE

    def _process_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        has_selection = selection.count_selected_rows() > 0
        self.process_end_button.set_sensitive(has_selection)
        self.process_kill_button.set_sensitive(has_selection)

    def _on_process_button_press(self, view: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button != Gdk.BUTTON_SECONDARY or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        target = view.get_path_at_pos(int(event.x), int(event.y))
        if target is None:
            return False
        path, _column, _cell_x, _cell_y = target
        view.grab_focus()
        view.get_selection().select_path(path)
        return self._popup_process_menu(event)

    def _on_process_popup_menu(self, _view: Gtk.TreeView) -> bool:
        return self._popup_process_menu()

    def _popup_process_menu(self, event: Gdk.EventButton | None = None) -> bool:
        process = self._selected_process()
        if process is None:
            return False

        menu = self._build_process_menu(process)
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(
                self.process_view,
                Gdk.Gravity.CENTER,
                Gdk.Gravity.CENTER,
                None,
            )
        return True

    @staticmethod
    def _build_signal_submenu(callback) -> Gtk.MenuItem:
        signal_item = Gtk.MenuItem(label="Send signal")
        submenu = Gtk.Menu()
        for signal_name, label in (
            ("HUP", "Hang up (HUP)"),
            ("INT", "Interrupt (INT)"),
            ("TERM", "Terminate (TERM)"),
            ("KILL", "Kill (KILL)"),
            ("USR1", "User 1 (USR1)"),
            ("USR2", "User 2 (USR2)"),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, name=signal_name: callback(name))
            submenu.append(item)
        signal_item.set_submenu(submenu)
        return signal_item

    def _build_process_menu(self, process: ProcessInfo) -> Gtk.Menu:
        menu = Gtk.Menu()
        end_item = Gtk.MenuItem(label="End process")
        end_item.connect("activate", lambda _item: self._confirm_process_action(False, process))
        menu.append(end_item)
        kill_item = Gtk.MenuItem(label="Force stop")
        kill_item.connect("activate", lambda _item: self._confirm_process_action(True, process))
        menu.append(kill_item)
        menu.append(Gtk.SeparatorMenuItem())

        stopped = process.state in ("Stopped", "Tracing")
        pause_item = Gtk.MenuItem(label="Pause process")
        pause_item.set_sensitive(not stopped)
        pause_item.connect("activate", lambda _item: self._control_process("pause", process))
        menu.append(pause_item)
        resume_item = Gtk.MenuItem(label="Resume process")
        resume_item.set_sensitive(stopped)
        resume_item.connect("activate", lambda _item: self._control_process("resume", process))
        menu.append(resume_item)
        menu.append(self._build_signal_submenu(lambda name: self._send_process_signal(process, name)))
        menu.append(Gtk.SeparatorMenuItem())

        details_item = Gtk.MenuItem(label="Details")
        details_item.connect("activate", lambda _item: self._open_process_details(process))
        menu.append(details_item)
        menu.show_all()
        self._process_context_menu = menu
        return menu

    def _send_process_signal(self, process: ProcessInfo, signal_name: str) -> None:
        self._send_signal_with_confirmation([process], signal_name, process.name)

    def _show_process_details(
        self,
        view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn | None,
    ) -> None:
        model = view.get_model()
        process = model.get_value(model.get_iter(path), 11)
        self._open_process_details(process)

    def _open_process_details(self, process: ProcessInfo) -> None:
        dialog = Gtk.Dialog(title=f"{process.name}  /  PID {process.pid}", transient_for=self, modal=True)
        dialog.get_style_context().add_class("process-details-dialog")
        close_button = dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        close_button.get_style_context().add_class("compact-button")
        dialog.get_action_area().get_style_context().add_class("process-details-actions")
        dialog.set_default_size(680, 520)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.get_style_context().add_class("process-details-body")
        body.set_border_width(16)
        details = DetailGrid(
            [
                ("pid", "Process ID"), ("ppid", "Parent ID"), ("user", "User"), ("state", "State"),
                ("cpu", "CPU"), ("memory", "Resident memory"), ("threads", "Threads"), ("started", "Started"),
                ("swap", "Swap"), ("read", "Total read I/O"), ("write", "Total write I/O"),
                ("user_cpu", "User CPU time"), ("system_cpu", "Kernel CPU time"),
                ("cgroup", "Control group"),
            ],
            columns=2,
        )
        details.update({
            "pid": str(process.pid),
            "ppid": str(process.ppid),
            "user": process.user,
            "state": process.state,
            "cpu": f"{process.cpu_percent:.1f}%",
            "memory": format_bytes(process.memory_bytes),
            "threads": str(process.threads),
            "started": datetime.fromtimestamp(process.started_at).strftime("%Y-%m-%d %H:%M:%S"),
            "swap": format_bytes(process.swap_bytes),
            "read": format_bytes(process.read_bytes),
            "write": format_bytes(process.write_bytes),
            "user_cpu": f"{process.user_cpu_seconds:.2f} s",
            "system_cpu": f"{process.system_cpu_seconds:.2f} s",
            "cgroup": process.control_group,
        })
        body.pack_start(details, False, False, 0)
        command_title = Gtk.Label(label="Command", xalign=0)
        command_title.get_style_context().add_class("detail-label")
        command = Gtk.Label(label=process.command, xalign=0)
        command.set_line_wrap(True)
        command.set_selectable(True)
        command.get_style_context().add_class("detail-value")
        body.pack_start(command_title, False, False, 0)
        command_scroller = scrollable(command)
        command_scroller.get_style_context().add_class("process-details-scroll")
        body.pack_start(command_scroller, True, True, 0)
        content_area = dialog.get_content_area()
        content_area.get_style_context().add_class("process-details-body")
        content_area.add(body)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _confirm_process_action(self, force: bool, process: ProcessInfo | None = None) -> None:
        process = process or self._selected_process()
        if process is None:
            self._message("Select a process first", "Choose a row in the process list before using this action.")
            return
        verb = "force stop" if force else "end"
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=f"{verb.title()} {process.name}?",
        )
        dialog.format_secondary_text(
            f"PID {process.pid} owned by {process.user}. "
            + ("Unsaved work may be lost immediately." if force else "The process will receive SIGTERM and may save its state.")
        )
        dialog.add_button("Force stop" if force else "End process", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            self.collector.terminate_process(process.pid, force)
        except (PermissionError, ProcessLookupError, OSError) as error:
            self._message("Process action failed", str(error), Gtk.MessageType.ERROR)
        self.request_update()

    def _control_process(self, action: str, process: ProcessInfo | None = None) -> None:
        process = process or self._selected_process()
        if process is None:
            self._message("Select a process first", "Choose a row in the process list before using this action.")
            return
        try:
            if action == "pause":
                self.collector.suspend_process(process.pid)
            elif action == "resume":
                self.collector.resume_process(process.pid)
            else:
                raise ValueError(f"Unsupported process action: {action}")
        except (PermissionError, ProcessLookupError, OSError) as error:
            self._message("Process action failed", str(error), Gtk.MessageType.ERROR)
        self.request_update()

    def _message(self, title: str, detail: str, kind=Gtk.MessageType.INFO) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=kind,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _render_users(self, processes: list[ProcessInfo]) -> None:
        grouped: dict[str, list[float | int]] = defaultdict(lambda: [0, 0.0, 0])
        for process in processes:
            values = grouped[process.user]
            values[0] += 1
            values[1] += process.cpu_percent
            values[2] += process.memory_bytes
        self.user_store.clear()
        for user, values in sorted(grouped.items(), key=lambda item: int(item[1][2]), reverse=True):
            self.user_store.append((user, int(values[0]), float(values[1]), int(values[2])))

    def _selected_startup_entry(self):
        model, tree_iter = self.startup_view.get_selection().get_selected()
        return model.get_value(tree_iter, 4) if tree_iter is not None else None

    def _startup_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        entry = self._selected_startup_entry()
        self.startup_enable_button.set_sensitive(entry is not None and not entry.enabled)
        self.startup_disable_button.set_sensitive(entry is not None and entry.enabled)
        self.startup_open_button.set_sensitive(entry is not None)

    def _set_startup_enabled(self, enabled: bool) -> None:
        entry = self._selected_startup_entry()
        if entry is None:
            self._message("Select a startup app first", "Choose a row before changing its startup state.")
            return
        try:
            self.collector.set_startup_enabled(entry, enabled)
        except (OSError, ValueError, configparser.Error) as error:
            self._message(
                "Unable to update startup app",
                str(error),
                Gtk.MessageType.ERROR,
            )
            return
        self._apply_startup_entries(self.collector.startup_entries(), entry.desktop_file.name)

    def _open_startup_location(self, _button: Gtk.Button) -> None:
        entry = self._selected_startup_entry()
        if entry is None:
            return
        directory = Gio.File.new_for_path(str(entry.desktop_file.parent))
        try:
            Gio.AppInfo.launch_default_for_uri(directory.get_uri(), None)
        except GLib.Error as error:
            self._message("Unable to open startup location", str(error), Gtk.MessageType.ERROR)

    def _refresh_startup_entries(self) -> None:
        self.startup_count_label.set_text("Refreshing startup entries...")
        threading.Thread(target=self._load_startup_entries, daemon=True).start()

    def _load_startup_entries(self) -> None:
        entries = self.collector.startup_entries()
        GLib.idle_add(self._apply_startup_entries, entries)

    def _apply_startup_entries(self, entries, selected_name: str | None = None) -> bool:
        if selected_name is None:
            selected = self._selected_startup_entry()
            selected_name = selected.desktop_file.name if selected is not None else None
        selected_path = None
        self.startup_store.clear()
        for item in entries:
            tree_iter = self.startup_store.append(
                (item.name, "Enabled" if item.enabled else "Disabled", item.source, item.command, item)
            )
            if item.desktop_file.name == selected_name:
                selected_path = self.startup_store.get_path(tree_iter)
        self.startup_count_label.set_text(
            f"{len(entries)} entries  /  {sum(item.enabled for item in entries)} enabled"
        )
        if selected_path is not None:
            self.startup_view.get_selection().select_path(selected_path)
        else:
            self._startup_selection_changed(self.startup_view.get_selection())
        return GLib.SOURCE_REMOVE

    def _render_current_services(self) -> None:
        processes = self.snapshot.processes if self.snapshot else []
        self._render_services(self._services, processes)

    @staticmethod
    def _service_process_map(processes: list[ProcessInfo]) -> dict[tuple[str, str], list[ProcessInfo]]:
        members: dict[tuple[str, str], list[ProcessInfo]] = defaultdict(list)
        for process in processes:
            membership = service_membership_from_control_group(process.control_group)
            if membership is not None:
                members[membership].append(process)
        return members

    def _expanded_service_keys(self) -> set[str]:
        expanded: set[str] = set()

        def remember(view: Gtk.TreeView, path: Gtk.TreePath, _data=None) -> None:
            tree_iter = view.get_model().get_iter(path)
            expanded.add(view.get_model().get_value(tree_iter, 9))

        self.service_view.map_expanded_rows(remember, None)
        return expanded

    def _render_services(self, services: list[ServiceInfo], processes: list[ProcessInfo]) -> None:
        selected_model, selected_iter = self.service_view.get_selection().get_selected()
        selected_key = selected_model.get_value(selected_iter, 9) if selected_iter is not None else None
        expanded_keys = self._expanded_service_keys()
        adjustment = self.service_scroller.get_vadjustment()
        previous_scroll = adjustment.get_value()
        mode = self.service_scope_combo.get_active_id() or "all"
        query = self.service_search.get_text().strip().casefold()
        process_map = self._service_process_map(processes)

        filtered: list[ServiceInfo] = []
        for service in services:
            members = process_map.get((service.scope, service.unit), [])
            if mode in {"user", "system"} and service.scope != mode:
                continue
            if mode == "active" and service.active != "active":
                continue
            if mode == "failed" and service.active != "failed" and service.state != "failed":
                continue
            searchable = " ".join(
                [service.unit, service.active, service.state, service.description, service.scope]
                + [f"{process.pid} {process.name} {process.command}" for process in members]
            ).casefold()
            if query and query not in searchable:
                continue
            filtered.append(service)

        self.service_store.clear()
        grouped = {
            "user": [service for service in filtered if service.scope == "user"],
            "system": [service for service in filtered if service.scope == "system"],
        }
        for scope, title, description in (
            ("user", "User services", "Current user's systemd manager"),
            ("system", "System services", "System-wide systemd manager / polkit protected"),
        ):
            scoped_services = grouped[scope]
            if not scoped_services:
                continue
            scope_members = [
                process
                for service in scoped_services
                for process in process_map.get((service.scope, service.unit), [])
            ]
            scope_key = f"scope:{scope}"
            scope_iter = self.service_store.append(
                None,
                (
                    title,
                    "",
                    f"{len(scoped_services)} units",
                    "",
                    sum(process.cpu_percent for process in scope_members),
                    sum(process.memory_bytes for process in scope_members),
                    description,
                    None,
                    None,
                    scope_key,
                    "folder-symbolic",
                ),
            )

            for service in scoped_services:
                members = process_map.get((service.scope, service.unit), [])
                service_key = f"service:{service.scope}:{service.unit}"
                service_icon = (
                    "dialog-error-symbolic"
                    if service.active == "failed" or service.state == "failed"
                    else "media-playback-start-symbolic"
                    if service.active == "active"
                    else "media-playback-stop-symbolic"
                )
                service_iter = self.service_store.append(
                    scope_iter,
                    (
                        service.unit,
                        "",
                        service.active,
                        service.state,
                        sum(process.cpu_percent for process in members),
                        sum(process.memory_bytes for process in members),
                        service.description,
                        service,
                        None,
                        service_key,
                        service_icon,
                    ),
                )
                roots, children = self._process_tree(members)
                visited: set[int] = set()

                def append_process(process: ProcessInfo, parent: Gtk.TreeIter) -> None:
                    if process.pid in visited:
                        return
                    visited.add(process.pid)
                    process_key = f"service-process:{service.scope}:{service.unit}:{process.pid}"
                    process_iter = self.service_store.append(
                        parent,
                        (
                            process.name,
                            str(process.pid),
                            "process",
                            process.state,
                            process.cpu_percent,
                            process.memory_bytes,
                            process.command,
                            service,
                            process,
                            process_key,
                            "system-run-symbolic",
                        ),
                    )
                    for child in children.get(process.pid, []):
                        append_process(child, process_iter)

                for root in roots:
                    append_process(root, service_iter)
                for process in members:
                    append_process(process, service_iter)

        paths = self._tree_paths_by_key(self.service_store, 9)
        if not self._service_initial_render_done:
            expanded_keys.update(key for key in paths if key.startswith("scope:"))
            self._service_initial_render_done = True
        expanded_paths = sorted(
            (paths[key] for key in expanded_keys if key in paths),
            key=lambda path: path.get_depth(),
        )
        for path in expanded_paths:
            self.service_view.expand_row(path, False)
        selected_path = paths.get(selected_key)
        if selected_path is not None:
            self.service_view.get_selection().select_path(selected_path)
        GLib.idle_add(self._restore_service_scroll, previous_scroll)
        active = sum(service.active == "active" for service in filtered)
        failed = sum(service.active == "failed" or service.state == "failed" for service in filtered)
        self.service_count_label.set_text(f"{len(filtered)} services  /  {active} active  /  {failed} failed")
        self.service_status.set_text(
            f"USER {sum(service.scope == 'user' for service in services)}  /  "
            f"SYSTEM {sum(service.scope == 'system' for service in services)}  /  "
            f"MEMBERSHIP FROM PROCESS CGROUPS  /  {datetime.now().strftime('%H:%M:%S')}"
        )
        self._service_selection_changed(self.service_view.get_selection())
        self._last_service_render = time.monotonic()

    def _restore_service_scroll(self, value: float) -> bool:
        adjustment = self.service_scroller.get_vadjustment()
        adjustment.set_value(
            clamped_scroll_value(value, adjustment.get_lower(), adjustment.get_upper(), adjustment.get_page_size())
        )
        return GLib.SOURCE_REMOVE

    def _selected_service_target(self) -> tuple[ServiceInfo | None, ProcessInfo | None]:
        model, tree_iter = self.service_view.get_selection().get_selected()
        if tree_iter is None:
            return None, None
        return model.get_value(tree_iter, 7), model.get_value(tree_iter, 8)

    def _service_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        service, process = self._selected_service_target()
        selectable_service = service is not None and process is None and not self._service_action_in_progress
        active = selectable_service and service.active == "active"
        self.service_start_button.set_sensitive(selectable_service and not active)
        self.service_stop_button.set_sensitive(bool(active))
        self.service_restart_button.set_sensitive(bool(active))
        self.service_details_button.set_sensitive(selectable_service)

    def _service_row_activated(
        self,
        view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn | None,
    ) -> None:
        model = view.get_model()
        tree_iter = model.get_iter(path)
        process = model.get_value(tree_iter, 8)
        service = model.get_value(tree_iter, 7)
        if process is not None:
            self._open_process_details(process)
        elif service is not None:
            self._open_service_details(service)
        elif view.row_expanded(path):
            view.collapse_row(path)
        else:
            view.expand_row(path, False)

    def _on_service_button_press(self, view: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button != Gdk.BUTTON_SECONDARY or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        target = view.get_path_at_pos(int(event.x), int(event.y))
        if target is None:
            return False
        path, _column, _cell_x, _cell_y = target
        view.grab_focus()
        view.get_selection().select_path(path)
        return self._popup_service_menu(event)

    def _on_service_popup_menu(self, _view: Gtk.TreeView) -> bool:
        return self._popup_service_menu()

    def _popup_service_menu(self, event: Gdk.EventButton | None = None) -> bool:
        service, process = self._selected_service_target()
        if process is not None:
            menu = self._build_process_menu(process)
        elif service is not None:
            menu = self._build_service_menu(service)
        else:
            return False
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(self.service_view, Gdk.Gravity.CENTER, Gdk.Gravity.CENTER, None)
        return True

    def _build_service_menu(self, service: ServiceInfo) -> Gtk.Menu:
        menu = Gtk.Menu()
        for action, label in (("start", "Start service"), ("stop", "Stop service"), ("restart", "Restart service")):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(
                (action == "start" and service.active != "active")
                or (action in {"stop", "restart"} and service.active == "active")
            )
            item.connect("activate", lambda _item, selected_action=action: self._confirm_service_action(selected_action, service))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        details_item = Gtk.MenuItem(label="Details")
        details_item.connect("activate", lambda _item: self._open_service_details(service))
        menu.append(details_item)
        menu.show_all()
        self._service_context_menu = menu
        return menu

    def _confirm_service_action(self, action: str, service: ServiceInfo | None = None) -> None:
        selected_service, process = self._selected_service_target()
        service = service or (selected_service if process is None else None)
        if service is None:
            self._message("Select a service", "Choose a service row rather than a process or scope row.")
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING if action in {"stop", "restart"} else Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.CANCEL,
            text=f"{action.title()} {service.unit}?",
        )
        dialog.format_secondary_text(
            f"Scope: {service.scope}. The request uses current systemd and polkit permissions; "
            "dependent applications or sessions may be affected."
        )
        dialog.add_button(action.title(), Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self._service_action_in_progress = True
        self.service_status.set_text(f"{action.upper()} {service.scope}:{service.unit}...")
        self._service_selection_changed(self.service_view.get_selection())
        threading.Thread(target=self._run_service_action, args=(service, action), daemon=True).start()

    def _run_service_action(self, service: ServiceInfo, action: str) -> None:
        error: str | None = None
        try:
            self.collector.control_service(service, action)
        except (RuntimeError, ValueError) as exception:
            error = str(exception)
        GLib.idle_add(self._finish_service_action, service, action, error)

    def _finish_service_action(self, service: ServiceInfo, action: str, error: str | None) -> bool:
        self._service_action_in_progress = False
        if error:
            self._message(
                f"Unable to {action} {service.unit}",
                error,
                Gtk.MessageType.ERROR,
            )
        self._refresh_services()
        return GLib.SOURCE_REMOVE

    def _refresh_services(self) -> None:
        self.service_count_label.set_text("Refreshing system and user services...")
        threading.Thread(target=self._load_services, daemon=True).start()

    def _load_services(self) -> None:
        GLib.idle_add(self._apply_services, self.collector.services())

    def _apply_services(self, services: list[ServiceInfo]) -> bool:
        self._services = services
        self._render_current_services()
        return GLib.SOURCE_REMOVE

    def _service_members(self, service: ServiceInfo) -> list[ProcessInfo]:
        if not self.snapshot:
            return []
        return self._service_process_map(self.snapshot.processes).get((service.scope, service.unit), [])

    def _open_selected_service_details(self) -> None:
        service, process = self._selected_service_target()
        if service is not None and process is None:
            self._open_service_details(service)

    def _open_service_details(self, service: ServiceInfo) -> None:
        members = self._service_members(service)
        dialog = Gtk.Dialog(title=service.unit, transient_for=self, modal=True)
        dialog.get_style_context().add_class("process-details-dialog")
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(670, 480)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(16)
        details = DetailGrid(
            [
                ("unit", "Unit"), ("scope", "Manager scope"),
                ("active", "Active state"), ("state", "Sub-state"),
                ("processes", "Member processes"), ("cpu", "Combined CPU"),
                ("memory", "Resident memory"), ("permission", "Control authorization"),
            ],
            columns=2,
        )
        details.update({
            "unit": service.unit,
            "scope": service.scope,
            "active": service.active,
            "state": service.state,
            "processes": str(len(members)),
            "cpu": f"{sum(process.cpu_percent for process in members):.1f}%",
            "memory": format_bytes(sum(process.memory_bytes for process in members)),
            "permission": "Current user" if service.scope == "user" else "systemd / polkit",
        })
        body.pack_start(details, False, False, 0)
        description_title = Gtk.Label(label="Description", xalign=0)
        description_title.get_style_context().add_class("detail-label")
        body.pack_start(description_title, False, False, 0)
        description = Gtk.Label(label=service.description, xalign=0)
        description.set_line_wrap(True)
        body.pack_start(description, False, False, 0)
        member_list = Gtk.Label(
            label="\n".join(f"{process.pid:<8} {process.name}  {process.command}" for process in members)
            or "No currently visible member processes",
            xalign=0,
        )
        member_list.set_selectable(True)
        member_list.set_line_wrap(True)
        body.pack_start(scrollable(member_list), True, True, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _load_slow_lists(self) -> None:
        startup = self.collector.startup_entries()
        services = self.collector.services()
        GLib.idle_add(self._apply_slow_lists, startup, services)

    def _apply_slow_lists(self, startup, services) -> bool:
        self._apply_startup_entries(startup)
        self._services = services
        self._render_current_services()
        return GLib.SOURCE_REMOVE

    def _on_key_press(self, _widget, event) -> bool:
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if control and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.show_page("processes")
            self.process_search.grab_focus()
            return True
        if event.keyval == Gdk.KEY_F5:
            self.request_update()
            return True
        return False


def main() -> int:
    window = TmogWindow()
    window.present()
    Gtk.main()
    return 0

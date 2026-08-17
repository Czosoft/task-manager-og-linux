"""Capture the live GTK window for visual regression checks."""

from __future__ import annotations

import sys
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk

from tmog_linux.app import TmogWindow


def main() -> int:
    if len(sys.argv) not in (2, 3, 4):
        raise SystemExit("usage: capture_ui.py OUTPUT.png [PAGE] [PERFORMANCE_RESOURCE]")
    output = Path(sys.argv[1])
    window = TmogWindow()
    if len(sys.argv) == 3:
        window.show_page(sys.argv[2])
    elif len(sys.argv) == 4:
        window.show_page(sys.argv[2])
        resource = sys.argv[3]
        if sys.argv[2] == "performance" and resource == "cpu-collapsed":
            window.resource_rows["cpu"].set_active(True)
            window.cpu_overall_section.collapse_button.clicked()
            window.cpu_logical_section.collapse_button.clicked()
        elif sys.argv[2] == "performance" and resource in window.resource_rows:
            window.resource_rows[resource].set_active(True)
        elif sys.argv[2] == "processes":
            window.process_view_combo.set_active_id(sys.argv[3])
    window.present()
    if window._timer_id is not None:
        GLib.source_remove(window._timer_id)

    def capture() -> bool:
        root = window.get_child()
        allocation = root.get_allocation()
        print(f"capturing {window.stack.get_visible_child_name()}")
        output.parent.mkdir(parents=True, exist_ok=True)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, allocation.width, allocation.height)
        context = cairo.Context(surface)
        root.draw(context)
        surface.write_to_png(str(output))
        window.destroy()
        return GLib.SOURCE_REMOVE

    def resample() -> bool:
        window.request_update()
        return GLib.SOURCE_REMOVE

    for delay in (800, 1700, 2600):
        GLib.timeout_add(delay, resample)
    GLib.timeout_add_seconds(4, capture)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

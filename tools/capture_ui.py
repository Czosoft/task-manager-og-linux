"""Capture the live GTK window for visual regression checks."""

from __future__ import annotations

import math
import os
import socket
import sys
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk

from tmog_linux.app import TmogWindow


def sanitize_public_capture(window: TmogWindow) -> None:
    """Replace machine-specific values before publishing documentation images."""
    current_user = window._current_user
    for row in window.process_store:
        if row[2] == current_user:
            row[2] = "demo"
        if "capture_ui.py" in row[10]:
            row[10] = "python3 tools/capture_ui.py screenshots/example.png"
        elif row[1].strip() == "python3" and "tmog_linux" in row[10]:
            row[10] = "python3 -m tmog_linux"

    for row in window.user_store:
        if row[0] == current_user:
            row[0] = "demo"

    window.perf_widgets["network"]["details"].update({
        "hardware": "02:00:00:00:00:01",
        "ipv4": "192.0.2.10",
        "ipv6": "2001:db8::10",
    })

    host_name = socket.gethostname()

    def sanitize_label(widget: Gtk.Widget) -> None:
        if isinstance(widget, Gtk.Label) and widget.get_text() == host_name:
            widget.set_text("demo-workstation")
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                sanitize_label(child)

    sanitize_label(window)


def main() -> int:
    if len(sys.argv) not in (2, 3, 4):
        raise SystemExit("usage: capture_ui.py OUTPUT.png [PAGE] [PERFORMANCE_RESOURCE]")
    output = Path(sys.argv[1])
    window = TmogWindow()
    capture_theme = os.environ.get("TMOG_CAPTURE_THEME")
    if capture_theme:
        if capture_theme not in ("system", "dark", "light"):
            raise SystemExit("TMOG_CAPTURE_THEME must be system, dark, or light")
        window._apply_theme(capture_theme)
    capture_size = os.environ.get("TMOG_CAPTURE_SIZE")
    if capture_size:
        try:
            width, height = (int(value) for value in capture_size.lower().split("x", 1))
        except ValueError as error:
            raise SystemExit("TMOG_CAPTURE_SIZE must use WIDTHxHEIGHT, for example 1920x1080") from error
        window.resize(width, height)
    capture_cpu_count_text = os.environ.get("TMOG_CAPTURE_CPU_COUNT")
    try:
        capture_cpu_count = int(capture_cpu_count_text) if capture_cpu_count_text else None
    except ValueError as error:
        raise SystemExit("TMOG_CAPTURE_CPU_COUNT must be a positive integer") from error
    if capture_cpu_count is not None and capture_cpu_count < 1:
        raise SystemExit("TMOG_CAPTURE_CPU_COUNT must be a positive integer")
    resource = None
    if len(sys.argv) == 3:
        window.show_page(sys.argv[2])
    elif len(sys.argv) == 4:
        window.show_page(sys.argv[2])
        resource = sys.argv[3]
        if sys.argv[2] == "performance" and resource == "cpu-overall-collapsed":
            window.resource_rows["cpu"].set_active(True)
            window.cpu_overall_section.collapse_button.clicked()
        elif sys.argv[2] == "performance" and resource == "cpu-collapsed":
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
        capture_widget = window if os.environ.get("TMOG_CAPTURE_TITLEBAR") == "1" else root
        allocation = capture_widget.get_allocation()
        print(f"capturing {window.stack.get_visible_child_name()} in {window._effective_theme} theme")
        for name, row in window.resource_rows.items():
            main_graph = window.perf_widgets[name]["graph"]
            if row.sparkline.fixed_max != main_graph.fixed_max:
                raise RuntimeError(
                    f"{name} sidebar graph scale {row.sparkline.fixed_max} "
                    f"does not match main graph scale {main_graph.fixed_max}"
                )
            if row.sparkline.values.maxlen != main_graph.primary.maxlen:
                raise RuntimeError(
                    f"{name} sidebar history {row.sparkline.values.maxlen} samples "
                    f"does not match main history {main_graph.primary.maxlen} samples"
                )
        if (
            window.stack.get_visible_child_name() == "performance"
            and window.performance_stack.get_visible_child_name() == "cpu"
            and window.core_graphs
        ):
            columns = window._core_grid_columns or 1
            rows = math.ceil(len(window.core_graphs) / columns)
            tile_height = max(graph.get_allocated_height() for graph in window.core_graphs)
            required_height = rows * tile_height + max(0, rows - 1) * window.core_grid.get_row_spacing()
            allocated_height = window.core_grid.get_allocated_height()
            _requested_width, requested_height = window.core_grid.get_size_request()
            print(
                f"core-grid: {len(window.core_graphs)} CPUs, density={window._core_grid_density}, "
                f"{columns} columns, {rows} rows, "
                f"required={required_height}px, requested={requested_height}px, "
                f"allocated={allocated_height}px"
            )
            if resource == "cpu-overall-collapsed" and window._core_grid_density != "expanded":
                raise RuntimeError("CPU grid did not expand after collapsing overall utilization")
            if requested_height < required_height:
                raise RuntimeError("CPU grid minimum height is smaller than its rows")
            if allocated_height < required_height:
                raise RuntimeError("CPU grid allocation clips its final row")
            details_card = window.perf_widgets["cpu"]["details"].get_parent()
            _minimum_details_height, natural_details_height = details_card.get_preferred_height()
            allocated_details_height = details_card.get_allocated_height()
            print(
                f"details-card: natural={natural_details_height}px, "
                f"allocated={allocated_details_height}px"
            )
            if allocated_details_height > natural_details_height + 1:
                raise RuntimeError("CPU details card expands beyond its content")
        output.parent.mkdir(parents=True, exist_ok=True)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, allocation.width, allocation.height)
        context = cairo.Context(surface)
        capture_widget.draw(context)
        surface.write_to_png(str(output))
        window.destroy()
        return GLib.SOURCE_REMOVE

    def resample() -> bool:
        window.request_update()
        return GLib.SOURCE_REMOVE

    def override_core_count() -> bool:
        values = [float((index * 7) % 31) for index in range(capture_cpu_count or 0)]
        window._update_core_graphs(values, [""] * len(values))
        return GLib.SOURCE_REMOVE

    for delay in (800, 1700, 2600):
        GLib.timeout_add(delay, resample)
    if capture_cpu_count is not None:
        GLib.timeout_add(3200, override_core_count)
    if os.environ.get("TMOG_CAPTURE_PUBLIC") == "1":
        GLib.timeout_add(3300, sanitize_public_capture, window)
    GLib.timeout_add_seconds(4, capture)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

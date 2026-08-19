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
    window._cpu_section_persistence_enabled = False
    window.cpu_overall_section.set_section_expanded(True)
    window.cpu_logical_section.set_section_expanded(True)
    capture_theme = os.environ.get("TMOG_CAPTURE_THEME")
    if capture_theme:
        if capture_theme not in ("system", "dark", "light"):
            raise SystemExit("TMOG_CAPTURE_THEME must be system, dark, or light")
        window._apply_theme(capture_theme)
    capture_size = os.environ.get("TMOG_CAPTURE_SIZE")
    if capture_size:
        window._summary_default_fit_enabled = False
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
            window.process_view_combo.set_active_id("all" if resource == "interactions" else resource)
    window.present()
    if window._timer_id is not None:
        GLib.source_remove(window._timer_id)

    def capture() -> bool:
        details_dialog = None
        if os.environ.get("TMOG_CAPTURE_PROCESS_DETAILS") == "1":
            dialogs = [
                widget
                for widget in Gtk.Window.list_toplevels()
                if isinstance(widget, Gtk.Dialog) and widget.get_visible()
            ]
            if not dialogs:
                raise RuntimeError("Process Details dialog did not open")
            details_dialog = dialogs[-1]
            capture_widget = details_dialog
        else:
            root = window.get_child()
            capture_widget = window if os.environ.get("TMOG_CAPTURE_TITLEBAR") == "1" else root
        allocation = capture_widget.get_allocation()
        print(f"capturing {window.stack.get_visible_child_name()} in {window._effective_theme} theme")
        if window.stack.get_visible_child_name() == "summary":
            adjustment = window.summary_scroller.get_vadjustment()
            overflow = max(0.0, adjustment.get_upper() - adjustment.get_page_size())
            print(
                f"summary-scroll: content={adjustment.get_upper():.0f}px, "
                f"viewport={adjustment.get_page_size():.0f}px, overflow={overflow:.0f}px"
            )
            if os.environ.get("TMOG_CAPTURE_ASSERT_SUMMARY_FITS") == "1" and overflow > 0.5:
                raise RuntimeError(f"Summary still scrolls vertically by {overflow:.0f}px")
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
        if os.environ.get("TMOG_CAPTURE_ASSERT_PROCESS_INTERACTIONS") == "1":
            expected_pid = process_interaction_state.get("pid")
            selected = window._selected_process()
            sort_column, sort_order = window.process_sort.get_sort_column_id()
            scroll_value = window.process_scroller.get_vadjustment().get_value()
            print(
                f"process-interactions: selected={selected.pid if selected else None}, "
                f"sort={sort_column}/{sort_order.value_nick}, scroll={scroll_value:.0f}px, "
                f"menu={process_interaction_state.get('menu')}"
            )
            if expected_pid is None or selected is None or selected.pid != expected_pid:
                raise RuntimeError("Process selection was not preserved across refresh")
            if sort_column != 5 or sort_order != Gtk.SortType.DESCENDING:
                raise RuntimeError("Process Memory descending sort was not preserved")
            if process_interaction_state.get("scroll", 0.0) > 0.5 and scroll_value <= 0.5:
                raise RuntimeError("Process scroll position returned to the first row")
        if window.stack.get_visible_child_name() == "processes" and resource == "tree":
            sort_column, _sort_order = window.process_sort.get_sort_column_id()
            if sort_column != 12:
                raise RuntimeError("Process tree mode was flattened by table sorting")
            if any(column.get_clickable() for column in window.process_view.get_columns()):
                raise RuntimeError("Process tree mode still exposes flat table sorting")
        output.parent.mkdir(parents=True, exist_ok=True)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, allocation.width, allocation.height)
        context = cairo.Context(surface)
        capture_widget.draw(context)
        surface.write_to_png(str(output))
        if details_dialog is not None:
            details_dialog.response(Gtk.ResponseType.CLOSE)
            GLib.idle_add(window.destroy)
        else:
            window.destroy()
        return GLib.SOURCE_REMOVE

    def resample() -> bool:
        window.request_update()
        return GLib.SOURCE_REMOVE

    def override_core_count() -> bool:
        values = [float((index * 7) % 31) for index in range(capture_cpu_count or 0)]
        window._update_core_graphs(values, [""] * len(values))
        return GLib.SOURCE_REMOVE

    process_interaction_state: dict[str, object] = {}

    def exercise_process_interactions() -> bool:
        if os.environ.get("TMOG_CAPTURE_ASSERT_PROCESS_INTERACTIONS") != "1":
            return GLib.SOURCE_REMOVE
        if window.stack.get_visible_child_name() != "processes" or window.snapshot is None:
            raise RuntimeError("Processes interaction check requires a populated Processes page")

        memory_column = window.process_view.get_column(5)
        memory_column.clicked()
        memory_column.clicked()
        sort_column, sort_order = window.process_sort.get_sort_column_id()
        if sort_column != 5 or sort_order != Gtk.SortType.DESCENDING:
            raise RuntimeError("Clicking the Memory header did not toggle to descending sort")
        row_count = window.process_sort.iter_n_children(None)
        if row_count < 3:
            raise RuntimeError("Processes interaction check needs at least three rows")
        path = Gtk.TreePath.new_from_indices([row_count // 2])
        tree_iter = window.process_sort.get_iter(path)
        process_interaction_state["pid"] = window.process_sort.get_value(tree_iter, 0)
        window.process_view.get_selection().select_path(path)

        adjustment = window.process_scroller.get_vadjustment()
        maximum = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
        target_scroll = min(maximum, max(1.0, adjustment.get_page_size() * 0.5))
        adjustment.set_value(target_scroll)
        process_interaction_state["scroll"] = target_scroll

        selected = window._selected_process()
        if selected is None:
            raise RuntimeError("Process context menu check lost its selected process")
        window._build_process_menu(selected)
        labels = [
            child.get_label()
            for child in window._process_context_menu.get_children()
            if isinstance(child, Gtk.MenuItem) and not isinstance(child, Gtk.SeparatorMenuItem)
        ]
        expected_labels = ["End process", "Force stop", "Pause process", "Resume process", "Details"]
        if labels != expected_labels:
            raise RuntimeError(f"Unexpected process context menu items: {labels}")
        process_interaction_state["menu"] = ", ".join(labels)

        window._render_processes(window.snapshot.processes)
        return GLib.SOURCE_REMOVE

    def open_process_details() -> bool:
        if os.environ.get("TMOG_CAPTURE_PROCESS_DETAILS") != "1":
            return GLib.SOURCE_REMOVE
        if window.snapshot is None or not window.snapshot.processes:
            raise RuntimeError("Process Details capture requires a populated process list")
        process = next(
            (item for item in window.snapshot.processes if item.pid == os.getpid()),
            window.snapshot.processes[0],
        )
        window._open_process_details(process)
        return GLib.SOURCE_REMOVE

    def prepare_startup_capture() -> bool:
        if window.stack.get_visible_child_name() != "startup":
            return GLib.SOURCE_REMOVE
        first = window.startup_store.get_iter_first()
        if first is not None:
            window.startup_view.get_selection().select_iter(first)
        return GLib.SOURCE_REMOVE

    def select_io_resource() -> bool:
        selection = os.environ.get("TMOG_CAPTURE_IO_SELECTION")
        if not selection or window.stack.get_visible_child_name() != "performance":
            return GLib.SOURCE_REMOVE
        resource_name = window.performance_stack.get_visible_child_name()
        if resource_name not in ("disk", "network"):
            raise RuntimeError("I/O selection capture requires the Disk or Network page")
        identifiers = getattr(window, f"_{resource_name}_combo_identifiers", [])
        if selection == "first-device":
            selection = next((identifier for identifier in identifiers if identifier != "combined"), None)
        elif selection == "largest-device":
            if resource_name != "disk" or window.snapshot is None:
                raise RuntimeError("Largest-device selection requires a populated Disk page")
            largest_disk = max(window.snapshot.disks, key=lambda disk: disk.capacity, default=None)
            selection = largest_disk.identifier if largest_disk is not None else None
        if selection not in identifiers:
            raise RuntimeError(f"I/O selection {selection!r} is unavailable: {identifiers}")
        combo = window.perf_widgets[resource_name]["device_combo"]
        combo.set_active_id(selection)
        history = window._io_histories[resource_name].get(selection)
        if history is None or window.perf_widgets[resource_name]["graph"].primary is not history[0]:
            raise RuntimeError("Selected I/O resource did not restore its independent history")
        print(
            f"io-selection: resource={resource_name}, selected={selection}, "
            f"samples={len(history[0])}, options={len(identifiers)}"
        )
        return GLib.SOURCE_REMOVE

    for delay in (800, 1700, 2600):
        GLib.timeout_add(delay, resample)
    if capture_cpu_count is not None:
        GLib.timeout_add(3200, override_core_count)
    GLib.timeout_add(3100, exercise_process_interactions)
    GLib.timeout_add(3200, prepare_startup_capture)
    GLib.timeout_add(3250, select_io_resource)
    if os.environ.get("TMOG_CAPTURE_PUBLIC") == "1":
        GLib.timeout_add(3300, sanitize_public_capture, window)
    GLib.timeout_add(3500, open_process_details)
    GLib.timeout_add_seconds(4, capture)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

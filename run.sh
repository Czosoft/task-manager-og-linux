#!/usr/bin/env bash
set -euo pipefail

app_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "TMOG Linux must be run on Linux." >&2
    exit 1
fi

if ! python3 -c 'import cairo, gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    echo "GTK 3 Python and Cairo bindings are missing." >&2
    echo "Install them with:" >&2
    echo "  sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0" >&2
    exit 1
fi

export PYTHONPATH="${app_root}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m tmog_linux "$@"

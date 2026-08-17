#!/usr/bin/env bash
set -euo pipefail

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_root="${XDG_DATA_HOME:-${HOME}/.local/share}"
install_root="${data_root}/tmog-linux"
bin_root="${HOME}/.local/bin"
desktop_root="${data_root}/applications"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer is for Linux only." >&2
    exit 1
fi

if ! python3 -c 'import cairo, gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    echo "Install the Ubuntu runtime first:" >&2
    echo "  sudo apt update" >&2
    echo "  sudo apt install python3 python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0" >&2
    exit 1
fi

install -d "${install_root}/tmog_linux" "${bin_root}" "${desktop_root}"
install -m 0644 "${source_root}"/tmog_linux/*.py "${install_root}/tmog_linux/"

launcher="${bin_root}/tmog-linux"
{
    printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail'
    printf 'export PYTHONPATH=%q\n' "${install_root}"
    printf '%s\n' 'exec python3 -m tmog_linux "$@"'
} > "${launcher}"
chmod 0755 "${launcher}"

desktop_file="${desktop_root}/tmog-linux.desktop"
{
    printf '%s\n' '[Desktop Entry]'
    printf '%s\n' 'Type=Application'
    printf '%s\n' 'Name=Task Manager OG // Linux'
    printf '%s\n' 'GenericName=System Monitor'
    printf '%s\n' 'Comment=Live Linux processes and system performance'
    printf 'Exec=%s\n' "${launcher}"
    printf '%s\n' 'Icon=utilities-system-monitor'
    printf '%s\n' 'Terminal=false'
    printf '%s\n' 'Categories=System;Monitor;GTK;'
    printf '%s\n' 'Keywords=task;process;cpu;memory;system;monitor;'
    printf '%s\n' 'StartupNotify=true'
} > "${desktop_file}"
chmod 0644 "${desktop_file}"

echo "Installed Task Manager OG // Linux."
echo "Open it from the application menu or run: tmog-linux"

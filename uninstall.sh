#!/usr/bin/env bash
set -euo pipefail

data_root="${XDG_DATA_HOME:-${HOME}/.local/share}"
install_root="${data_root}/tmog-linux"
launcher="${HOME}/.local/bin/tmog-linux"
desktop_file="${data_root}/applications/tmog-linux.desktop"

rm -rf -- "${install_root}"
rm -f -- "${launcher}" "${desktop_file}"
echo "Task Manager OG // Linux was removed from this user account."

#!/bin/bash
# NetForge uninstall
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)

if [ "$(id -u)" -ne 0 ]; then
    exec sudo bash "$0" "$@"
fi

echo "Stopping portal if running ..."
/usr/local/lib/netforge/portal-helper stop 2>/dev/null || true

echo "Removing helper + sudoers ..."
rm -f /usr/local/lib/netforge/portal-helper
rm -f /usr/local/lib/netforge/portal.sh
rmdir /usr/local/lib/netforge 2>/dev/null || true
rm -f /etc/sudoers.d/netforge

echo "Removing desktop entries ..."
rm -f "$HOME_DIR/Desktop/NetForge.desktop"
rm -f "$HOME_DIR/.local/share/applications/netforge.desktop"

echo "Note: project files and venv in $DIR are left intact."
echo "Delete the folder manually if you want a full wipe."
echo "Done."

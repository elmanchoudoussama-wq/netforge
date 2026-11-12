#!/bin/bash
# NetForge one-shot installer
# - system packages
# - nodogsplash from source if needed
# - passwordless helper for portal (limited sudoers)
# - desktop icon + menu entry
# - python venv + deps

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
LIB_DIR="/usr/local/lib/netforge"
BIN_DIR="/usr/local/bin"

echo "=============================================="
echo "  NetForge Installer"
echo "=============================================="
echo "Install for user: $USER_NAME"
echo "Project path    : $DIR"
echo

if [ "$(id -u)" -ne 0 ]; then
    echo "Re-running with sudo ..."
    exec sudo bash "$0" "$@"
fi

# ── 1. packages ───────────────────────────────────────────────────────────
echo "[1/6] System packages ..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    hostapd dnsmasq iptables bluez bluez-tools network-manager \
    iw rfkill python3 python3-venv python3-tk \
    git build-essential libmicrohttpd-dev make \
    aircrack-ng wireless-tools \
    >/dev/null

systemctl disable --now hostapd dnsmasq 2>/dev/null || true
systemctl unmask hostapd 2>/dev/null || true

# ── 2. nodogsplash ────────────────────────────────────────────────────────
if ! command -v nodogsplash >/dev/null 2>&1; then
    echo "[2/6] Compiling nodogsplash ..."
    tmp=$(mktemp -d)
    git clone --depth 1 https://github.com/nodogsplash/nodogsplash.git "$tmp"
    (cd "$tmp" && make && make install)
    rm -rf "$tmp"
else
    echo "[2/6] nodogsplash already present"
fi

# ── 3. privileged helper + sudoers ────────────────────────────────────────
echo "[3/6] Installing privileged helper (passwordless for this user) ..."
mkdir -p "$LIB_DIR"
cp "$DIR/modules/portal/portal.sh" "$LIB_DIR/portal.sh"
chmod 755 "$LIB_DIR/portal.sh"

# small wrapper that sources env file written by the GUI
cat > "$LIB_DIR/portal-helper" <<'HELPER'
#!/bin/bash
# NetForge portal helper — runs as root via sudoers NOPASSWD
ENV_FILE="/tmp/netforge-portal.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi
exec /usr/local/lib/netforge/portal.sh "$@"
HELPER
chmod 755 "$LIB_DIR/portal-helper"

# Resolve absolute paths for capture tools (needed for secure sudoers)
AIRMON=$(command -v airmon-ng || echo /usr/sbin/airmon-ng)
AIRODUMP=$(command -v airodump-ng || echo /usr/sbin/airodump-ng)
AIREPLAY=$(command -v aireplay-ng || echo /usr/sbin/aireplay-ng)
AIRCRACK=$(command -v aircrack-ng || echo /usr/bin/aircrack-ng)
IW=$(command -v iw || echo /usr/sbin/iw)
SYSTEMCTL=$(command -v systemctl || echo /bin/systemctl)

# sudoers rule — portal helper + capture tools (passwordless for this user only)
SUDOERS_FILE="/etc/sudoers.d/netforge"
cat > "$SUDOERS_FILE" <<EOF
# NetForge — limited passwordless access
# Portal
$USER_NAME ALL=(root) NOPASSWD: $LIB_DIR/portal-helper
# Capture / handshake (monitor mode, deauth, scan)
$USER_NAME ALL=(root) NOPASSWD: $AIRMON, $AIRODUMP, $AIREPLAY, $AIRCRACK, $IW
$USER_NAME ALL=(root) NOPASSWD: /bin/systemctl restart NetworkManager, /usr/bin/systemctl restart NetworkManager
$USER_NAME ALL=(root) NOPASSWD: /bin/chown, /usr/bin/chown
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/tail, /bin/tail
EOF
chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE" || { echo "sudoers validation failed"; rm -f "$SUDOERS_FILE"; exit 1; }
echo "  sudoers: portal-helper + airmon/airodump/aireplay/aircrack/iw"

# Ensure auth log exists and is readable by the GUI user
touch /var/log/bt-portal-auth.log /var/log/bt-portal.log 2>/dev/null || true
chmod 644 /var/log/bt-portal-auth.log /var/log/bt-portal.log 2>/dev/null || true


# ── 4. Python venv ────────────────────────────────────────────────────────
echo "[4/6] Python venv + dependencies ..."
if [ ! -d "$DIR/venv" ]; then
    sudo -u "$USER_NAME" python3 -m venv "$DIR/venv"
fi
sudo -u "$USER_NAME" "$DIR/venv/bin/pip" install --upgrade pip
sudo -u "$USER_NAME" "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"

# ── 5. desktop entry ──────────────────────────────────────────────────────
echo "[5/6] Desktop icon + application menu ..."
LAUNCHER="$DIR/launch.sh"
chmod +x "$LAUNCHER"
chmod +x "$DIR/main.py" 2>/dev/null || true
chmod +x "$DIR/modules/portal/portal.sh"

ICON="$DIR/assets/icon.svg"
[ -f "$ICON" ] || ICON="network-wireless"

TMP=$(mktemp)
cat > "$TMP" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=NetForge
Comment=Network lab toolkit — Portal · Capture · Transform · Analyzer
Exec=$LAUNCHER
Icon=$ICON
Terminal=false
Categories=Network;System;Security;
StartupNotify=true
EOF

# Desktop
if [ -d "$HOME_DIR/Desktop" ]; then
    DEST="$HOME_DIR/Desktop/NetForge.desktop"
    cp "$TMP" "$DEST"
    chown "$USER_NAME:" "$DEST"
    chmod 755 "$DEST"
    if command -v gio >/dev/null 2>&1; then
        sudo -u "$USER_NAME" gio set "$DEST" metadata::trusted true 2>/dev/null || true
    fi
    echo "  Desktop : $DEST"
fi

# App menu
APPDIR="$HOME_DIR/.local/share/applications"
mkdir -p "$APPDIR"
cp "$TMP" "$APPDIR/netforge.desktop"
chown -R "$USER_NAME:" "$APPDIR"
chmod 755 "$APPDIR/netforge.desktop"
echo "  App menu: $APPDIR/netforge.desktop"
rm -f "$TMP"

# ── 6. done ───────────────────────────────────────────────────────────────
echo "[6/6] Done."
echo
echo "=============================================="
echo "  NetForge is ready"
echo "=============================================="
echo "  Launch from desktop icon or:"
echo "    $LAUNCHER"
echo
echo "  Portal start/stop — no password needed."
echo "  Capture (monitor/deauth) — no password needed."
echo "  Launch the app as a normal user (do NOT use sudo)."
echo
echo "  Uninstall:  sudo bash $DIR/uninstall.sh"
echo "=============================================="

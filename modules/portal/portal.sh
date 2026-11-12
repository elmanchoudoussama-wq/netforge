#!/bin/bash
# NetForge Portal — non-interactive backend
# Called by the privileged helper or directly with env vars:
#   NF_SSID  NF_PASS  NF_TRIES  NF_MODE  NF_IFACE

set -euo pipefail

CONF_DIR="/etc/bt-portal"
FAIL_DIR="/var/lib/bt-portal"
SETTINGS="$CONF_DIR/settings.conf"
LOG="/var/log/bt-portal.log"
AUTH_LOG="/var/log/bt-portal-auth.log"
VERIFY_PORT=8091

SSID="${NF_SSID:-FreeWiFi}"
PORTAL_PASS="${NF_PASS:-1234}"
MAX_TRIES="${NF_TRIES:-1}"
INTERNET_MODE="${NF_MODE:-bluetooth}"
MANUAL_IFACE="${NF_IFACE:-}"

mkdir -p "$CONF_DIR" "$FAIL_DIR"
touch "$AUTH_LOG" "$LOG" 2>/dev/null || true
chmod 644 "$AUTH_LOG" "$LOG" 2>/dev/null || true

say()  { echo "==> $*" | tee -a "$LOG"; }
fail() { echo "ERROR: $*" | tee -a "$LOG"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Must run as root (use the installed helper)"

load_settings() {
    cat > "$SETTINGS" <<EOF
SSID="$SSID"
PORTAL_PASS="$PORTAL_PASS"
MAX_TRIES=$MAX_TRIES
EOF
    chmod 600 "$SETTINGS"
}

detect_wlan() {
    WLAN=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}')
    [ -n "$WLAN" ] || fail "No Wi-Fi interface found"
    say "Wi-Fi interface: $WLAN"
}

detect_phone() {
    if [ -z "${PHONE_MAC:-}" ]; then
        bluetoothctl power on >/dev/null 2>&1 || true
        local list
        list=$(bluetoothctl devices Paired 2>/dev/null || true)
        [ -z "$list" ] && list=$(bluetoothctl devices 2>/dev/null || true)
        [ -n "$list" ] || return 1
        PHONE_MAC=$(echo "$list" | head -n1 | awk '{print $2}')
        [ -n "$PHONE_MAC" ] && echo "PHONE_MAC=\"$PHONE_MAC\"" >> "$SETTINGS"
    fi
    say "Phone: $PHONE_MAC"
}

find_bnep() { ip -o link show 2>/dev/null | awk -F': ' '$2 ~ /^bnep/{print $2; exit}'; }

connect_bluetooth() {
    say "Connecting Bluetooth ..."
    rfkill unblock bluetooth wifi >/dev/null 2>&1 || true
    systemctl restart bluetooth 2>/dev/null || true
    sleep 2
    systemctl start NetworkManager >/dev/null 2>&1 || true
    bluetoothctl power on >/dev/null 2>&1 || true
    bluetoothctl trust "$PHONE_MAC" >/dev/null 2>&1 || true
    bluetoothctl connect "$PHONE_MAC" >/dev/null 2>&1 || true
    sleep 2

    nmcli connection delete btportal >/dev/null 2>&1 || true
    nmcli connection add type bluetooth con-name btportal \
        bluetooth.bdaddr "$PHONE_MAC" bluetooth.type panu autoconnect no >>"$LOG" 2>&1 || true
    nmcli connection up btportal >>"$LOG" 2>&1 || true

    for i in $(seq 1 15); do
        BT_IF=$(find_bnep); [ -n "$BT_IF" ] && break; sleep 1
    done

    if [ -z "$BT_IF" ]; then
        pkill -f "bt-network" 2>/dev/null || true
        nohup bt-network -c "$PHONE_MAC" nap >>"$LOG" 2>&1 &
        for i in $(seq 1 20); do
            BT_IF=$(find_bnep); [ -n "$BT_IF" ] && break; sleep 1
        done
        if [ -n "$BT_IF" ]; then
            ip link set "$BT_IF" up
            dhclient "$BT_IF" >>"$LOG" 2>&1 || true
        fi
    fi

    [ -n "$BT_IF" ] || return 1
    for i in $(seq 1 15); do
        ip -4 addr show "$BT_IF" | grep -q inet && break
        sleep 1
    done
    ip -4 addr show "$BT_IF" | grep -q inet || return 1
    say "Bluetooth OK on $BT_IF"
    return 0
}

pick_subnet() {
    local used
    used=$(ip -4 route | awk '{print $1}')
    for s in 192.168.50 192.168.77 10.77.0 172.28.5; do
        echo "$used" | grep -q "^$s\." || { SUBNET=$s; break; }
    done
    SUBNET=${SUBNET:-192.168.99}
    GW_IP="$SUBNET.1"
    say "Hotspot: $SUBNET.0/24 (gw $GW_IP)"
}

write_portal_files() {
    mkdir -p /etc/nodogsplash/htdocs

    cat > "$CONF_DIR/portal.conf" <<EOF
PORTAL_PASS="$PORTAL_PASS"
MAX_TRIES=$MAX_TRIES
FAIL_DIR="$FAIL_DIR"
LOG_FILE="$AUTH_LOG"
GW_IP="$GW_IP"
GW_PORT=2050
EOF
    chmod 600 "$CONF_DIR/portal.conf"

    cat > /usr/local/bin/nds-binauth.sh <<'EOF'
#!/bin/sh
. /etc/bt-portal/portal.conf
METHOD="$1"; MAC="$2"
LOG="${LOG_FILE:-/var/log/bt-portal-auth.log}"
TS=$(date '+%F %T')
case "$METHOD" in
  auth_client)
    printf '[%s] RESULT=ALLOW MAC=%s\n' "$TS" "$MAC" >> "$LOG" 2>/dev/null
    chmod 644 "$LOG" 2>/dev/null || true
    echo "0 0 0"; exit 0 ;;
  *) exit 0 ;;
esac
EOF
    chmod 755 /usr/local/bin/nds-binauth.sh

    cat > /etc/nodogsplash/htdocs/splash.html <<EOF
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wi-Fi Login</title>
<style>
body{font-family:system-ui,sans-serif;background:#0a0e17;color:#e5e7eb;display:flex;justify-content:center;padding:48px 16px;margin:0}
.box{background:#111827;padding:28px;border-radius:16px;max-width:360px;width:100%;border:1px solid #1f2937}
h2{margin:0 0 8px;color:#00e5a8;font-weight:600}
p{color:#9ca3af;margin:0 0 16px;font-size:14px}
input,button{width:100%;padding:14px;margin-top:10px;font-size:15px;box-sizing:border-box;border-radius:10px;border:1px solid #374151;background:#0f172a;color:#e5e7eb}
button{background:linear-gradient(135deg,#00e5a8,#3b82f6);color:#0a0e17;border:0;font-weight:600;cursor:pointer}
</style></head><body><div class="box">
<h2>NetForge Access</h2>
<p>Enter the access key</p>
<form method="get" action="http://$GW_IP:$VERIFY_PORT/verify">
<input type="hidden" name="tok" value="\$tok">
<input type="hidden" name="redir" value="\$redir">
<input type="password" name="pass" placeholder="Access key" required>
<button type="submit">Connect</button>
</form></div></body></html>
EOF

    cat > /etc/nodogsplash/htdocs/success.html <<'EOF'
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Connected</title>
<style>body{font-family:system-ui;background:#0a0e17;color:#e5e7eb;text-align:center;padding:80px 20px}
h2{color:#00e5a8}</style></head>
<body><h2>✓ Connected</h2><p>Internet access granted.</p></body></html>
EOF

    # Verify server (same logic as before)
    cat > /usr/local/bin/nds-verify.py <<'PYEOF'
#!/usr/bin/env python3
import http.server, urllib.parse, subprocess, os, time, sys
CONF = {}
with open('/etc/bt-portal/portal.conf') as f:
    for line in f:
        line = line.strip()
        if not line or '=' not in line: continue
        k, v = line.split('=', 1)
        CONF[k] = v.strip().strip('"')
PORTAL_PASS = CONF.get('PORTAL_PASS', '')
MAX_TRIES = int(CONF.get('MAX_TRIES', '1') or '1')
FAIL_DIR = CONF.get('FAIL_DIR', '/var/lib/bt-portal')
LOG_FILE = CONF.get('LOG_FILE', '/var/log/bt-portal-auth.log')
GW_IP = CONF.get('GW_IP', '127.0.0.1')
GW_PORT = CONF.get('GW_PORT', '2050')

def log(line):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_FILE, 'a') as f: f.write('[%s] %s\n' % (ts, line))
        try: os.chmod(LOG_FILE, 0o644)
        except: pass
    except: pass

def mac_for_token(tok):
    try:
        out = subprocess.run(['ndsctl', 'clients'], capture_output=True, text=True, timeout=3).stdout
    except: return None
    mac = token = None
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith('mac='): mac = line.split('=',1)[1]
        elif line.startswith('token='): token = line.split('=',1)[1]
        if mac and token:
            if token == tok: return mac
            mac = token = None
    return None

FORM = '''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Wi-Fi Login</title>
<style>body{font-family:system-ui;background:#0a0e17;color:#e5e7eb;display:flex;justify-content:center;padding:48px 16px}
.box{background:#111827;padding:28px;border-radius:16px;max-width:360px;width:100%;border:1px solid #1f2937}
h2{color:#00e5a8;margin:0 0 8px}.err{color:#ef4444;font-size:14px;margin:8px 0}
input,button{width:100%;padding:14px;margin-top:10px;font-size:15px;box-sizing:border-box;border-radius:10px;border:1px solid #374151;background:#0f172a;color:#e5e7eb}
button{background:linear-gradient(135deg,#00e5a8,#3b82f6);color:#0a0e17;border:0;font-weight:600}</style></head>
<body><div class="box"><h2>NetForge Access</h2>{msg}
<form method="get" action="/verify">
<input type="hidden" name="tok" value="{tok}"><input type="hidden" name="redir" value="{redir}">
<input type="password" name="pass" placeholder="Access key" required autofocus>
<button type="submit">Connect</button></form></div></body></html>'''

BLOCKED = '''<!DOCTYPE html><html><head><meta charset="utf-8"><title>Blocked</title></head>
<body style="font-family:system-ui;background:#0a0e17;color:#e5e7eb;text-align:center;padding:60px">
<h2 style="color:#ef4444">Blocked</h2><p>Too many wrong attempts.</p></body></html>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/verify':
            self.send_response(404); self.end_headers(); return
        qs = urllib.parse.parse_qs(parsed.query)
        tok = qs.get('tok', [''])[0]
        redir = qs.get('redir', [''])[0]
        pw = qs.get('pass', [''])[0]
        mac = mac_for_token(tok) or 'unknown'
        if PORTAL_PASS and pw == PORTAL_PASS:
            try: os.remove(os.path.join(FAIL_DIR, mac))
            except: pass
            log('RESULT=ALLOW MAC=%s' % mac)
            target = 'http://%s:%s/nodogsplash_auth/?tok=%s&redir=%s' % (
                GW_IP, GW_PORT, urllib.parse.quote(tok), urllib.parse.quote(redir, safe=''))
            self.send_response(302); self.send_header('Location', target); self.end_headers(); return
        failfile = os.path.join(FAIL_DIR, mac)
        n = 0
        try:
            with open(failfile) as f: n = int((f.read() or '0').strip())
        except: n = 0
        n += 1
        try:
            with open(failfile, 'w') as f: f.write(str(n))
        except: pass
        if n >= MAX_TRIES:
            subprocess.run(['ndsctl', 'block', mac], capture_output=True)
            log('RESULT=DENY MAC=%s PASS=%r TRIES=%d/%d' % (mac, pw, n, MAX_TRIES))
            body = BLOCKED
        else:
            log('RESULT=DENY MAC=%s PASS=%r TRIES=%d/%d' % (mac, pw, n, MAX_TRIES))
            body = FORM.format(msg='<p class="err">Wrong password. %d left.</p>' % (MAX_TRIES-n), tok=tok, redir=redir)
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(body.encode())

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
    http.server.HTTPServer(('0.0.0.0', port), Handler).serve_forever()
PYEOF
    chmod 755 /usr/local/bin/nds-verify.py
}

start_hotspot() {
    say "Starting hotspot on $WLAN ..."
    cat > "$CONF_DIR/hostapd.conf" <<EOF
interface=$WLAN
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
EOF

    if [ -n "${BT_IF:-}" ]; then
        DNS_LINES="server=8.8.8.8
server=1.1.1.1"
    else
        DNS_LINES="address=/#/$GW_IP"
    fi

    cat > "$CONF_DIR/dnsmasq.conf" <<EOF
interface=$WLAN
listen-address=$GW_IP
bind-interfaces
dhcp-range=$SUBNET.20,$SUBNET.200,255.255.255.0,12h
dhcp-option=3,$GW_IP
dhcp-option=6,$GW_IP
$DNS_LINES
no-resolv
pid-file=/run/bt-portal-dnsmasq.pid
dhcp-leasefile=$CONF_DIR/dnsmasq.leases
EOF

    nmcli dev set "$WLAN" managed no >/dev/null 2>&1 || true
    pkill -f "wpa_supplicant.*$WLAN" 2>/dev/null || true
    pkill hostapd 2>/dev/null || true
    ip addr flush dev "$WLAN" 2>/dev/null || true
    ip link set "$WLAN" up
    ip addr add "$GW_IP/24" dev "$WLAN"

    hostapd -B "$CONF_DIR/hostapd.conf" >>"$LOG" 2>&1 || fail "hostapd failed"
    [ -f /run/bt-portal-dnsmasq.pid ] && pkill -F /run/bt-portal-dnsmasq.pid 2>/dev/null || true
    dnsmasq -C "$CONF_DIR/dnsmasq.conf" >>"$LOG" 2>&1 || fail "dnsmasq failed"

    sysctl -qw net.ipv4.ip_forward=1
    if [ -n "${BT_IF:-}" ]; then
        iptables -t nat -C POSTROUTING -o "$BT_IF" -j MASQUERADE 2>/dev/null \
            || iptables -t nat -A POSTROUTING -o "$BT_IF" -j MASQUERADE
        say "NAT via $BT_IF"
    else
        say "Offline mode (no NAT)"
    fi
}

start_portal() {
    say "Starting Nodogsplash ..."
    cat > /etc/nodogsplash/nodogsplash.conf <<EOF
GatewayInterface $WLAN
GatewayAddress $GW_IP
GatewayName $SSID
MaxClients 30
BinAuth /usr/local/bin/nds-binauth.sh
RedirectURL http://$GW_IP:2050/success.html
SessionTimeout 0
FirewallRuleSet authenticated-users {
    FirewallRule allow all
}
FirewallRuleSet preauthenticated-users {
    FirewallRule allow tcp port 53
    FirewallRule allow udp port 53
    FirewallRule allow tcp port $VERIFY_PORT
}
FirewallRuleSet users-to-router {
    FirewallRule allow udp port 53
    FirewallRule allow udp port 67
    FirewallRule allow tcp port 80
    FirewallRule allow tcp port $VERIFY_PORT
}
EOF
    rm -f "$FAIL_DIR"/* 2>/dev/null || true
    systemctl stop nodogsplash >/dev/null 2>&1 || true
    ndsctl stop >/dev/null 2>&1 || true
    systemctl restart nodogsplash >>"$LOG" 2>&1 || nodogsplash -c /etc/nodogsplash/nodogsplash.conf >>"$LOG" 2>&1
    sleep 2
    ndsctl status >/dev/null 2>&1 || fail "Nodogsplash failed"
}

start_verify() {
    pkill -f "nds-verify.py" 2>/dev/null || true
    sleep 1
    nohup python3 /usr/local/bin/nds-verify.py "$VERIFY_PORT" >>"$LOG" 2>&1 &
    disown
    sleep 1
    pgrep -f "nds-verify.py" >/dev/null || fail "verify server failed"
}

do_stop() {
    say "Stopping portal ..."
    ndsctl stop >/dev/null 2>&1 || true
    systemctl stop nodogsplash >/dev/null 2>&1 || true
    pkill -f "nds-verify.py" 2>/dev/null || true
    pkill hostapd 2>/dev/null || true
    [ -f /run/bt-portal-dnsmasq.pid ] && pkill -F /run/bt-portal-dnsmasq.pid 2>/dev/null || true
    for iface in $(ip -o link 2>/dev/null | awk -F': ' '{print $2}'); do
        iptables -t nat -D POSTROUTING -o "$iface" -j MASQUERADE 2>/dev/null || true
    done
    sysctl -qw net.ipv4.ip_forward=0
    nmcli connection down btportal >/dev/null 2>&1 || true
    pkill -f bt-network 2>/dev/null || true
    detect_wlan 2>/dev/null || true
    if [ -n "${WLAN:-}" ]; then
        ip addr flush dev "$WLAN" 2>/dev/null || true
        nmcli dev set "$WLAN" managed yes >/dev/null 2>&1 || true
    fi
    say "Stopped"
}

do_start() {
    load_settings
    detect_wlan

    BT_IF=""
    case "$INTERNET_MODE" in
        bluetooth)
            if detect_phone && connect_bluetooth; then
                say "Mode: Bluetooth ($BT_IF)"
            else
                say "Bluetooth failed → offline"
                INTERNET_MODE="offline"
            fi
            ;;
        existing)
            BT_IF=$(ip route show default 2>/dev/null | awk '{print $5; exit}' || true)
            if [ -z "$BT_IF" ] || [ "$BT_IF" = "$WLAN" ]; then
                INTERNET_MODE="offline"; BT_IF=""
            else
                say "Mode: existing ($BT_IF)"
            fi
            ;;
        manual)
            BT_IF="$MANUAL_IFACE"
            if [ -z "$BT_IF" ] || ! ip link show "$BT_IF" >/dev/null 2>&1; then
                INTERNET_MODE="offline"; BT_IF=""
            else
                say "Mode: manual ($BT_IF)"
            fi
            ;;
        *)
            INTERNET_MODE="offline"; BT_IF=""
            say "Mode: offline"
            ;;
    esac

    pick_subnet
    write_portal_files
    start_hotspot
    start_portal
    start_verify
    say "READY | SSID=$SSID | Pass=$PORTAL_PASS | Mode=$INTERNET_MODE"
}

case "${1:-}" in
    start)  do_start ;;
    stop)   do_stop ;;
    status)
        ndsctl status 2>/dev/null || echo "nodogsplash: not running"
        ndsctl clients 2>/dev/null || true
        pgrep -af "nds-verify.py" || echo "verify: not running"
        ;;
    forget)
        if [ "${2:-}" = "all" ]; then
            for M in $(ndsctl clients 2>/dev/null | awk -F= '/^mac=/{print $2}'); do
                ndsctl deauth "$M" >/dev/null 2>&1 || true
                ndsctl unblock "$M" >/dev/null 2>&1 || true
            done
            rm -f "$FAIL_DIR"/* 2>/dev/null || true
            echo "All forgotten"
        else
            M=$(echo "${2:-}" | tr 'A-F' 'a-f')
            ndsctl deauth "$M" >/dev/null 2>&1 || true
            ndsctl unblock "$M" >/dev/null 2>&1 || true
            rm -f "$FAIL_DIR/$M" 2>/dev/null || true
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|status|forget [all|MAC]}"
        exit 1
        ;;
esac

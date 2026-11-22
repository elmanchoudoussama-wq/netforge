# NetForge

**Unified network lab toolkit** — Captive Portal · Handshake Capture · Transform Engine · HTTP Analyzer

One application. One desktop icon. Runs without typing `sudo` after install.

---

## Features

| Module | What it does |
|--------|--------------|
| **Portal** | Share phone Bluetooth (or any) internet as a password-protected Wi-Fi hotspot with real captive portal |
| **Capture** | Monitor-mode handshake capture (aircrack-ng) with live AP list |
| **Transform** | GPU/CPU accelerated WPA key recovery (OpenCL) with background worker + auto-resume |
| **Analyzer** | Closed-lab HTTP traffic analyzer (passive / ARP-lab / probe) |

---

## Requirements

- Debian / Ubuntu / Kali (apt-based)
- Python 3.10+
- Wi-Fi card that supports AP mode (for Portal) and/or monitor mode (for Capture)
- Optional: OpenCL runtime for GPU acceleration

---


## Quick Install

```bash
git clone https://github.com/elmanchoudoussama-wq/netforge.git
cd netforge
bash install.sh
```

The installer will:

1. Install system packages (`hostapd`, `dnsmasq`, `aircrack-ng`, `bluez`, …)
2. Compile & install `nodogsplash` if needed
3. Create a limited **sudoers** rule so the app can start/stop privileged services **without asking for a password**
4. Install a desktop icon + application menu entry
5. Create a Python venv and install Python dependencies

After install you can launch **NetForge** from the desktop icon or menu. No terminal required.

---

## Run without install (dev)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Privileged actions will still need `sudo` / `pkexec` until you run `install.sh`.

---

## Uninstall

```bash
bash uninstall.sh
```

---

## Legal

Only use on networks and devices you own or have explicit written permission to test.  
Unauthorized access is a criminal offense in nearly every country.

---

## Project layout

```
netforge/
├── main.py                 # Unified futuristic GUI
├── install.sh              # One-shot installer
├── uninstall.sh
├── launch.sh               # Desktop launcher
├── netforge.desktop
├── requirements.txt
├── modules/
│   ├── portal/             # BT / Wi-Fi captive portal
│   ├── transform/          # Transform engine + worker
│   ├── capture/            # Handshake capture UI + engine
│   ├── analyzer/           # Lab HTTP analyzer
│   ├── gpucore/            # OpenCL helpers
│   └── xform/              # Transform pipeline
├── assets/
└── systemd/                # Optional background worker service
```

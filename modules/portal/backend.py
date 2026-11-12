#!/usr/bin/env python3
"""
NetForge Portal backend — non-interactive control of the captive portal stack.
Called by the GUI and by the privileged helper.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

CONF_DIR = Path("/etc/bt-portal")
FAIL_DIR = Path("/var/lib/bt-portal")
SETTINGS = CONF_DIR / "settings.conf"
LOG = Path("/var/log/bt-portal.log")
AUTH_LOG = Path("/var/log/bt-portal-auth.log")
VERIFY_PORT = 8091
HELPER = "/usr/local/lib/netforge/portal-helper"
ENV_FILE = Path("/tmp/netforge-portal.env")


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except Exception as e:
        return 1, str(e)


def _write_env(env: dict[str, str]) -> None:
    """Write env vars for the privileged helper to source."""
    lines = [f'{k}="{v}"' for k, v in env.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(ENV_FILE, 0o644)
    except OSError:
        pass


def _helper_cmd(*args: str) -> list[str]:
    """Build the command that invokes the helper with passwordless sudo."""
    return ["sudo", "-n", HELPER, *args]


def start(
    ssid: str = "FreeWiFi",
    password: str = "1234",
    max_tries: int = 1,
    mode: str = "bluetooth",          # bluetooth | existing | manual | offline
    manual_iface: str = "",
) -> tuple[bool, str]:
    """Start the portal via the privileged helper."""
    env = {
        "NF_SSID": ssid,
        "NF_PASS": password,
        "NF_TRIES": str(max_tries),
        "NF_MODE": mode,
        "NF_IFACE": manual_iface,
    }

    # Prefer the installed helper (passwordless after install.sh)
    if Path(HELPER).is_file():
        _write_env(env)
        code, out = _run(_helper_cmd("start"), timeout=120)
        return code == 0, out

    # Fallback: direct bash script (still needs root)
    script = Path(__file__).resolve().parent / "portal.sh"
    if script.is_file():
        _write_env(env)
        code, out = _run(["sudo", "-n", "bash", str(script), "start"], timeout=120)
        if code != 0 and "password is required" in out.lower():
            return False, (
                "Portal helper not installed and sudo needs a password.\n"
                "Run:  sudo bash install.sh"
            )
        return code == 0, out

    return False, "Portal helper not installed. Run: sudo bash install.sh"


def stop() -> tuple[bool, str]:
    if Path(HELPER).is_file():
        code, out = _run(_helper_cmd("stop"))
        return code == 0, out
    script = Path(__file__).resolve().parent / "portal.sh"
    if script.is_file():
        code, out = _run(["sudo", "-n", "bash", str(script), "stop"])
        return code == 0, out
    return False, "Portal helper not found"


def status() -> str:
    if Path(HELPER).is_file():
        _, out = _run(_helper_cmd("status"))
        return out
    # lightweight check
    lines = []
    try:
        r = subprocess.run(["pgrep", "-af", "nds-verify.py"], capture_output=True, text=True)
        lines.append("verify: " + (r.stdout.strip() or "not running"))
    except Exception:
        pass
    try:
        r = subprocess.run(["ndsctl", "status"], capture_output=True, text=True, timeout=3)
        lines.append(r.stdout or r.stderr or "")
    except Exception:
        lines.append("ndsctl: not available")
    return "\n".join(lines)


def is_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "nds-verify.py"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def forget_all() -> tuple[bool, str]:
    if Path(HELPER).is_file():
        code, out = _run(_helper_cmd("forget", "all"))
        return code == 0, out
    return False, "Helper not installed"


def read_auth_log(tail: int = 80) -> str:
    """Return last N lines of the auth log. File is world-readable after install."""
    try:
        with open(AUTH_LOG) as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except FileNotFoundError:
        return ""
    except PermissionError:
        # Should not happen after install (644). Nudge the user once.
        return "(auth log not readable — run: sudo chmod 644 /var/log/bt-portal-auth.log)"
    except Exception as e:
        return str(e)


class PortalBackend:
    start = staticmethod(start)
    stop = staticmethod(stop)
    status = staticmethod(status)
    is_running = staticmethod(is_running)
    forget_all = staticmethod(forget_all)
    read_auth_log = staticmethod(read_auth_log)

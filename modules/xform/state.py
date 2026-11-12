"""
xform.state
----------
Persistent progress + job memory.
- progress.json      : current / last job (resume after reboot)
- jobs/              : one JSON per handshake (history of positions)
- running.lock       : PID of active worker
- worker.log         : append-only log from background worker
"""
import json
import os
import time
import hashlib
from pathlib import Path

STATE_DIR = Path.home() / ".transform_engine"
STATE_FILE = STATE_DIR / "progress.json"
LOCK_FILE = STATE_DIR / "running.lock"
LOG_FILE = STATE_DIR / "worker.log"
JOBS_DIR = STATE_DIR / "jobs"


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def job_id_from(trace_path: str, basis: str) -> str:
    """Stable id for a specific handshake + SSID."""
    key = f"{os.path.abspath(trace_path)}|{basis}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def save_state(data: dict):
    ensure_state_dir()
    data["saved_at"] = time.time()
    data["saved_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(STATE_FILE)

    # also keep per-handshake memory
    jid = data.get("job_id")
    if jid:
        jpath = JOBS_DIR / f"{jid}.json"
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_job(job_id: str) -> dict | None:
    p = JOBS_DIR / f"{job_id}.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_jobs() -> list:
    ensure_state_dir()
    out = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def clear_state():
    if STATE_FILE.exists():
        STATE_FILE.unlink(missing_ok=True)
    if LOCK_FILE.exists():
        LOCK_FILE.unlink(missing_ok=True)


def set_running(running: bool, pid: int | None = None):
    ensure_state_dir()
    if running:
        LOCK_FILE.write_text(str(pid or os.getpid()), encoding="utf-8")
    else:
        LOCK_FILE.unlink(missing_ok=True)


def get_running_pid() -> int | None:
    if not LOCK_FILE.exists():
        return None
    try:
        pid = int(LOCK_FILE.read_text().strip())
        # check process still alive
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        LOCK_FILE.unlink(missing_ok=True)
        return None


def is_running() -> bool:
    return get_running_pid() is not None


def append_log(line: str):
    ensure_state_dir()
    ts = time.strftime("%H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")


def read_log_tail(n: int = 80) -> str:
    if not LOG_FILE.exists():
        return ""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def clear_log():
    if LOG_FILE.exists():
        LOG_FILE.write_text("", encoding="utf-8")

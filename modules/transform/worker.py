#!/usr/bin/env python3
"""
Headless background worker.
Can be started by the GUI or by systemd after reboot.

Usage:
  python worker.py              # resume from saved progress.json
  python worker.py --from-gui   # started by GUI (same)
"""
import os
import sys
import time
import signal
import traceback

# ensure project root on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_PROJECT, os.path.join(_PROJECT, "modules")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
ROOT = _PROJECT

from xform.state import (
    load_state, save_state, set_running, get_running_pid,
    append_log, clear_log, job_id_from, STATE_DIR,
)
from xform.pipeline import extract_descriptor
from xform.solver import Solver
from xform.generator import numeric_range_generator, file_generator

try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

_stop = False


def notify(title, message):
    append_log(f"NOTIFY: {title} — {message}")
    if HAS_PLYER:
        try:
            notification.notify(title=title, message=message, timeout=12,
                                app_name="Transform Studio")
        except Exception:
            pass
    # also try notify-send
    try:
        import subprocess
        subprocess.Popen(
            ["notify-send", "-a", "Transform Studio", title, message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _handle_signal(signum, frame):
    global _stop
    append_log(f"Signal {signum} — saving and stopping")
    _stop = True


def run_job(state: dict, resume_notify: bool = False):
    global _stop
    _stop = False

    set_running(True, os.getpid())
    append_log(f"Worker PID {os.getpid()} started")

    if resume_notify:
        tested = state.get("tested", 0)
        last = state.get("last_symbol", "?")
        notify(
            "Transform Studio — Resumed",
            f"Continuing after reboot/restart.\n"
            f"Already tested: {tested:,}\nLast: {last}",
        )

    # reload descriptor from trace
    trace = state.get("trace")
    if not trace or not os.path.isfile(trace):
        append_log(f"ERROR: trace missing: {trace}")
        notify("Transform Studio", f"Cannot resume: capture not found:\n{trace}")
        set_running(False)
        return

    desc, err = extract_descriptor(trace)
    if err:
        append_log(f"ERROR: extract failed: {err}")
        notify("Transform Studio", f"Cannot parse capture: {err}")
        set_running(False)
        return

    basis = state.get("basis") or desc.get("tag", "")
    if basis:
        desc = dict(desc)
        desc["basis"] = basis.encode("utf-8", "ignore") if isinstance(basis, str) else basis

    mode = state.get("mode", "numeric")
    tested = state.get("tested", 0)
    last_sym = state.get("last_symbol")

    if mode == "numeric":
        start = int(state.get("start", 1))
        end = int(state.get("end", 1_000_000_000))
        width = int(state.get("width", 0))
        if last_sym and str(last_sym).isdigit():
            start = int(last_sym) + 1
        gen = numeric_range_generator(start, end, width=width if width > 0 else 0)
        total = max(0, end - start + 1)
    else:
        path = state.get("path")
        if not path or not os.path.isfile(path):
            append_log(f"ERROR: wordlist missing: {path}")
            set_running(False)
            return
        # skip already-tested lines
        gen = file_generator(path, start_line=tested)
        total = -1

    job_meta = {
        "job_id": state.get("job_id") or job_id_from(trace, basis if isinstance(basis, str) else basis.decode()),
        "mode": mode,
        "trace": trace,
        "basis": basis if isinstance(basis, str) else basis.decode("utf-8", "ignore"),
        "start": state.get("start"),
        "end": state.get("end"),
        "width": state.get("width"),
        "path": state.get("path"),
        "status": "running",
    }

    cpu = int(state.get("cpu_percent", 30))
    backend = state.get("backend", "auto")

    def on_progress(done, total_est, last, speed=0.0):
        if done % 50000 < 20000:
            append_log(f"progress tested={done:,}  speed={speed:,.0f}/s  last={last}")

    try:
        solver = Solver(
            desc,
            backend=backend,
            device_index=int(state.get("device_index", 0)),
            log=append_log,
            stop_flag=lambda: _stop,
            cpu_percent=cpu,
            notify_cb=lambda msg: notify("Transform Studio", msg),
            save_every=20000,
        )
        found = solver.solve_generator(
            gen,
            total_estimate=total,
            resume_info={"tested": tested, "last_symbol": last_sym},
            on_progress=on_progress,
            job_meta=job_meta,
        )

        st = load_state() or {}
        if found:
            st["found"] = found
            st["status"] = "found"
            st["tested"] = st.get("tested", tested)
            save_state(st)
            append_log(f"FOUND: {found}")
            notify("Transform Studio — KEY FOUND", f"scalar = {found}")
        elif _stop:
            st["status"] = "stopped"
            save_state(st)
            append_log("Stopped by user/signal — progress saved")
            notify("Transform Studio", "Job stopped. Progress saved.")
        else:
            st["status"] = "completed"
            st["found"] = None
            save_state(st)
            append_log("Finished — no match")
            notify("Transform Studio", "Job finished — no match in range/wordlist.")
    except Exception as e:
        append_log(f"WORKER ERROR: {e}")
        append_log(traceback.format_exc())
        notify("Transform Studio — Error", str(e)[:200])
        st = load_state() or job_meta
        st["status"] = "error"
        st["error"] = str(e)
        save_state(st)
    finally:
        set_running(False)
        append_log("Worker exited")


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # already running?
    existing = get_running_pid()
    if existing and existing != os.getpid():
        append_log(f"Another worker already running (PID {existing})")
        print(f"Already running PID {existing}")
        sys.exit(0)

    state = load_state()
    if not state:
        append_log("No saved progress to resume")
        print("No saved job. Start a job from the GUI first.")
        sys.exit(1)

    if state.get("found"):
        append_log(f"Job already found key: {state['found']}")
        print(f"Already found: {state['found']}")
        sys.exit(0)

    if state.get("status") == "completed":
        append_log("Job already completed with no match")
        print("Job already completed.")
        sys.exit(0)

    # detect resume (reboot / service start)
    resume_notify = "--resume" in sys.argv or state.get("status") in ("running", "stopped", None)

    # mark running before long work
    state["status"] = "running"
    save_state(state)

    run_job(state, resume_notify=resume_notify)


if __name__ == "__main__":
    main()

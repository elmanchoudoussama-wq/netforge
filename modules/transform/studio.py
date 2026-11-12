#!/usr/bin/env python3
"""
Iterated Vector Transform Studio
- Start job → runs in background worker (survives closing the window)
- Progress saved per handshake; resume after reboot via systemd
- Notifications on resume / every 30 min / when key found
"""
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import time
import os
import sys
import signal
import subprocess
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[2]
for _p in (_PROJECT, _PROJECT / "modules"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
ROOT = _PROJECT

from xform.pipeline import extract_descriptor
from xform.generator import numeric_range_generator, file_generator
from xform.state import (
    load_state, clear_state, save_state, set_running,
    is_running, get_running_pid, append_log, read_log_tail,
    job_id_from, list_jobs, LOG_FILE, STATE_DIR,
)
from gpucore import DeviceContext, GPUError

try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False


def notify(title: str, message: str):
    if HAS_PLYER:
        try:
            notification.notify(title=title, message=message, timeout=10,
                                app_name="Transform Studio")
        except Exception:
            pass
    try:
        subprocess.Popen(
            ["notify-send", "-a", "Transform Studio", title, message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    print(f"[NOTIFY] {title}: {message}")


def _python_exe():
    for p in (ROOT / "venv" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
        if p.is_file():
            return str(p)
    return sys.executable


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Iterated Vector Transform Studio")
        self.root.geometry("940x860")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.trace_path = tk.StringVar()
        self.symbol_path = tk.StringVar()
        self.basis_var = tk.StringVar()
        self.backend_var = tk.StringVar(value="auto")
        self.device_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="numeric")
        self.length_var = tk.IntVar(value=8)
        self.start_num = tk.StringVar(value="1")
        self.end_num = tk.StringVar(value="1000000000")
        self.cpu_pct = tk.IntVar(value=30)
        self.bg_var = tk.BooleanVar(value=True)  # default background
        self.descriptor = None
        self.devices = []
        self._poll_id = None

        self._build_ui()
        self._refresh_status()
        self._start_poll()

    def _build_ui(self):
        tk.Label(self.root, text="Iterated Vector Transform Studio",
                 font=("Helvetica", 16, "bold")).pack(pady=8)

        f = tk.LabelFrame(self.root, text=" Parameters ", font=("Helvetica", 11, "bold"),
                          padx=12, pady=10)
        f.pack(fill="x", padx=16, pady=6)

        tk.Label(f, text="Signal trace (.cap/.pcap):").grid(row=0, column=0, sticky="w", pady=3)
        tk.Entry(f, textvariable=self.trace_path, width=50).grid(row=0, column=1, padx=4)
        tk.Button(f, text="Load", command=self._load_trace, width=9).grid(row=0, column=2)

        tk.Label(f, text="Basis (SSID):").grid(row=1, column=0, sticky="w", pady=3)
        tk.Entry(f, textvariable=self.basis_var, width=50).grid(row=1, column=1, padx=4)

        tk.Label(f, text="Candidate source:").grid(row=2, column=0, sticky="w", pady=3)
        mf = tk.Frame(f)
        mf.grid(row=2, column=1, columnspan=2, sticky="w")
        tk.Radiobutton(mf, text="Numeric sequence (1 → N)", variable=self.mode_var,
                       value="numeric", command=self._toggle_mode).pack(side="left")
        tk.Radiobutton(mf, text="External wordlist file", variable=self.mode_var,
                       value="file", command=self._toggle_mode).pack(side="left", padx=12)

        self.num_frame = tk.Frame(f)
        self.num_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        tk.Label(self.num_frame, text="Start:").pack(side="left")
        tk.Entry(self.num_frame, textvariable=self.start_num, width=12).pack(side="left", padx=4)
        tk.Label(self.num_frame, text="End (max 1e9):").pack(side="left", padx=(10, 0))
        tk.Entry(self.num_frame, textvariable=self.end_num, width=14).pack(side="left", padx=4)
        tk.Label(self.num_frame, text="Zero-pad width:").pack(side="left", padx=(10, 0))
        tk.Spinbox(self.num_frame, from_=0, to=16, textvariable=self.length_var,
                   width=4).pack(side="left", padx=4)

        self.file_frame = tk.Frame(f)
        self.file_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=2)
        tk.Label(self.file_frame, text="Symbol stream file:").pack(side="left")
        tk.Entry(self.file_frame, textvariable=self.symbol_path, width=42).pack(side="left", padx=4)
        tk.Button(self.file_frame, text="Browse", command=self._load_symbols, width=8).pack(side="left")

        tk.Label(f, text="Backend:").grid(row=5, column=0, sticky="w", pady=3)
        bf = tk.Frame(f)
        bf.grid(row=5, column=1, sticky="w")
        for v, t in [("auto", "Auto"), ("gpu", "GPU"), ("cpu", "CPU")]:
            tk.Radiobutton(bf, text=t, variable=self.backend_var, value=v).pack(side="left", padx=4)

        tk.Label(f, text="CPU limit %:").grid(row=6, column=0, sticky="w", pady=3)
        tk.Scale(f, from_=5, to=100, orient="horizontal", variable=self.cpu_pct,
                 length=220, showvalue=True).grid(row=6, column=1, sticky="w")

        tk.Label(f, text="Compute device:").grid(row=7, column=0, sticky="w", pady=3)
        self.device_combo = ttk.Combobox(f, textvariable=self.device_var, width=48, state="readonly")
        self.device_combo.grid(row=7, column=1, padx=4)
        self._populate_devices()

        tk.Checkbutton(
            f,
            text="Background worker (keeps running after you close this window; auto-resume after reboot if service installed)",
            variable=self.bg_var,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=4)

        # Status bar
        sf = tk.LabelFrame(self.root, text=" Job status ", font=("Helvetica", 11, "bold"),
                           padx=10, pady=6)
        sf.pack(fill="x", padx=16, pady=4)
        self.status_label = tk.Label(sf, text="Idle", font=("Consolas", 10), anchor="w", justify="left")
        self.status_label.pack(fill="x")

        # Buttons
        btnf = tk.Frame(self.root)
        btnf.pack(pady=6)
        self.run_btn = tk.Button(btnf, text="Start / Resume", font=("Helvetica", 11, "bold"),
                                 bg="#007bff", fg="white", padx=14, pady=6, command=self._start)
        self.run_btn.pack(side="left", padx=4)
        self.stop_btn = tk.Button(btnf, text="Stop", font=("Helvetica", 11, "bold"),
                                  bg="#dc3545", fg="white", padx=14, pady=6,
                                  command=self._stop_run)
        self.stop_btn.pack(side="left", padx=4)
        tk.Button(btnf, text="Refresh status", command=self._refresh_status).pack(side="left", padx=4)
        tk.Button(btnf, text="Clear progress", command=self._clear_progress).pack(side="left", padx=4)
        tk.Button(btnf, text="Job history", command=self._show_history).pack(side="left", padx=4)
        tk.Button(
            btnf, text="Capture handshake", font=("Helvetica", 10, "bold"),
            bg="#0d9488", fg="white", padx=10, pady=6,
            command=self._open_capture,
        ).pack(side="left", padx=8)

        pf = tk.Frame(self.root)
        pf.pack(fill="x", padx=16)
        self.progress = ttk.Progressbar(pf, orient="horizontal", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.rate_label = tk.Label(pf, text="", font=("Consolas", 10, "bold"))
        self.rate_label.pack(side="right", padx=8)

        lf = tk.LabelFrame(self.root, text=" Log (live from background worker) ",
                           font=("Helvetica", 11, "bold"), padx=8, pady=6)
        lf.pack(fill="both", expand=True, padx=16, pady=6)
        self.log_area = scrolledtext.ScrolledText(lf, wrap=tk.WORD, bg="#121212", fg="#00ff66",
                                                  font=("Consolas", 10), height=16)
        self.log_area.pack(fill="both", expand=True)

        self._toggle_mode()

    def _toggle_mode(self):
        if self.mode_var.get() == "numeric":
            self.num_frame.grid()
            self.file_frame.grid_remove()
        else:
            self.num_frame.grid_remove()
            self.file_frame.grid()

    def log(self, m):
        self.log_area.insert(tk.END, m + "\n")
        self.log_area.see(tk.END)

    def _populate_devices(self):
        try:
            tmp = DeviceContext(0)
            self.devices = tmp.all_devices
            self.device_combo["values"] = [f"{d['platform']} :: {d['name']}" for d in self.devices]
            if self.devices:
                self.device_combo.current(0)
            tmp.fns["clReleaseCommandQueue"](tmp.queue)
            tmp.fns["clReleaseContext"](tmp.context)
        except Exception as e:
            self.devices = []
            self.device_combo["values"] = [f"[no GPU: {e}]"]
            self.device_combo.current(0)

    def _load_trace(self):
        f = filedialog.askopenfilename(
            title="Select signal trace",
            filetypes=[("Trace bundles", "*.cap *.pcap"), ("All files", "*.*")])
        if not f:
            return
        self.trace_path.set(f)
        d, err = extract_descriptor(f)
        if err:
            self.log(f"[!] {err}")
            messagebox.showerror("Error", err)
            return
        self.descriptor = d
        if not self.basis_var.get():
            self.basis_var.set(d["tag"])
        self.log(f"[+] Descriptor loaded — basis={d['tag']!r}")
        self.log(f"    AP MAC  = {d['u_left'].hex()}")
        self.log(f"    CL MAC  = {d['u_right'].hex()}")
        self.log(f"    ANonce  = {d['n_left'].hex()[:16]}…")
        self.log(f"    SNonce  = {d['n_right'].hex()[:16]}…")
        self.log(f"    MIC     = {d['target'].hex()}")
        # show previous memory for this handshake if any
        jid = job_id_from(f, d["tag"])
        from xform.state import load_job
        prev = load_job(jid)
        if prev:
            self.log(f"[*] Memory for this handshake: tested={prev.get('tested', 0):,} "
                     f"status={prev.get('status')} last={prev.get('last_symbol')}")
            if prev.get("found"):
                self.log(f"[*] Previously FOUND: {prev['found']}")

    def _load_symbols(self):
        f = filedialog.askopenfilename(
            title="Select symbol stream",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if f:
            self.symbol_path.set(f)
            self.log(f"[*] Symbol stream: {f}")

    def _refresh_status(self):
        st = load_state()
        pid = get_running_pid()
        lines = []
        if pid:
            lines.append(f"● WORKER RUNNING  PID={pid}")
        else:
            lines.append("○ Worker not running")
        if st:
            speed = st.get("speed") or 0
            lines.append(f"  status     : {st.get('status', '?')}")
            lines.append(f"  tested     : {st.get('tested', 0):,}")
            lines.append(f"  speed      : {speed:,.0f} tries/s" if speed else "  speed      : —")
            lines.append(f"  last       : {st.get('last_symbol')}")
            lines.append(f"  mode       : {st.get('mode')}  basis={st.get('basis')!r}")
            if st.get("mode") == "numeric":
                lines.append(f"  range      : {st.get('start')} → {st.get('end')}  (pad={st.get('width')})")
            else:
                lines.append(f"  wordlist   : {st.get('path')}")
            if st.get("found"):
                lines.append(f"  FOUND      : {st['found']}")
            lines.append(f"  saved at   : {st.get('saved_iso')}")
            # progress bar
            if st.get("mode") == "numeric" and st.get("end") and st.get("start") is not None:
                total = int(st["end"]) - int(st["start"]) + 1
                done = int(st.get("tested") or 0)
                self.progress["maximum"] = max(total, 1)
                self.progress["value"] = min(done, total)
                spd = f"  |  {speed:,.0f}/s" if speed else ""
                self.rate_label.config(text=f"{done:,} / {total:,}{spd}")
            else:
                self.progress["maximum"] = 100
                self.progress["value"] = 0
                spd = f"  {speed:,.0f}/s" if speed else ""
                self.rate_label.config(text=f"tested {st.get('tested', 0):,}{spd}")
        else:
            lines.append("  (no saved job)")
            self.progress["value"] = 0
            self.rate_label.config(text="")
        self.status_label.config(text="\n".join(lines))

        # refresh log from worker
        tail = read_log_tail(60)
        if tail:
            self.log_area.delete("1.0", tk.END)
            self.log_area.insert(tk.END, tail + "\n")
            self.log_area.see(tk.END)

    def _start_poll(self):
        self._refresh_status()
        self._poll_id = self.root.after(3000, self._start_poll)

    def _clear_progress(self):
        if is_running():
            messagebox.showwarning("Busy", "Stop the worker first.")
            return
        clear_state()
        self.log("[*] Progress cleared.")
        self._refresh_status()

    def _show_history(self):
        jobs = list_jobs()
        if not jobs:
            messagebox.showinfo("History", "No saved handshake jobs yet.")
            return
        win = tk.Toplevel(self.root)
        win.title("Handshake job memory")
        win.geometry("640x400")
        txt = scrolledtext.ScrolledText(win, font=("Consolas", 10))
        txt.pack(fill="both", expand=True)
        for j in jobs:
            txt.insert(tk.END,
                       f"job={j.get('job_id')}  status={j.get('status')}  "
                       f"tested={j.get('tested', 0):,}  found={j.get('found')}\n"
                       f"  basis={j.get('basis')!r}\n"
                       f"  last={j.get('last_symbol')}  saved={j.get('saved_iso')}\n"
                       f"  trace={j.get('trace')}\n\n")

    def _open_capture(self):
        """Open futuristic handshake capture window."""
        try:
            from capture.ui import open_capture_window
        except Exception as e:
            messagebox.showerror("Capture module", str(e))
            return

        def on_hs(path: str):
            # auto-fill trace path in main UI
            self.trace_path.set(path)
            self.log(f"[+] Handshake ready: {path}")
            try:
                d, err = extract_descriptor(path)
                if not err and d:
                    self.descriptor = d
                    if not self.basis_var.get():
                        self.basis_var.set(d["tag"])
                    self.log(f"[+] Descriptor auto-loaded — basis={d['tag']!r}")
            except Exception as ex:
                self.log(f"[!] Could not auto-load descriptor: {ex}")

        open_capture_window(parent=self.root, on_handshake=on_hs)

    def _start(self):
        if is_running():
            messagebox.showinfo("Already running", "Worker is already active. Use Refresh status.")
            self._refresh_status()
            return

        # Resume existing unfinished job?
        st = load_state()
        if st and not st.get("found") and st.get("status") != "completed":
            if messagebox.askyesno(
                "Resume?",
                f"Saved job found:\n"
                f"  tested={st.get('tested', 0):,}\n"
                f"  last={st.get('last_symbol')}\n"
                f"  status={st.get('status')}\n\n"
                f"Resume this job in background?",
            ):
                self._spawn_worker()
                return

        # New job
        if not self.descriptor and self.trace_path.get():
            d, err = extract_descriptor(self.trace_path.get())
            if err:
                messagebox.showerror("Error", err)
                return
            self.descriptor = d

        if not self.descriptor:
            messagebox.showerror("Error", "Load a signal trace first.")
            return

        mode = self.mode_var.get()
        if mode == "file" and not self.symbol_path.get():
            messagebox.showerror("Error", "Select a wordlist file.")
            return

        basis = self.basis_var.get() or self.descriptor["tag"]
        jid = job_id_from(self.trace_path.get(), basis)

        job = {
            "job_id": jid,
            "mode": mode,
            "trace": self.trace_path.get(),
            "basis": basis,
            "backend": self.backend_var.get(),
            "device_index": max(0, self.device_combo.current()),
            "cpu_percent": self.cpu_pct.get(),
            "tested": 0,
            "last_symbol": None,
            "found": None,
            "status": "pending",
        }
        if mode == "numeric":
            try:
                start = int(self.start_num.get())
                end = min(int(self.end_num.get()), 1_000_000_000)
            except ValueError:
                messagebox.showerror("Error", "Invalid start/end.")
                return
            job.update({"start": start, "end": end, "width": self.length_var.get()})
        else:
            job["path"] = self.symbol_path.get()

        save_state(job)
        from xform.state import clear_log
        clear_log()
        append_log(f"New job {jid} mode={mode} basis={basis!r}")
        self._spawn_worker()

    def _spawn_worker(self):
        py = _python_exe()
        worker = str(ROOT / "modules" / "transform" / "worker.py")
        # detach so closing GUI does not kill worker
        logf = open(STATE_DIR / "worker_stdout.log", "a")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [py, worker],
            cwd=str(ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # independent process group
        )
        set_running(True, proc.pid)
        append_log(f"Spawned worker PID {proc.pid}")
        self.log(f"[*] Background worker started (PID {proc.pid})")
        self.log("[*] You can close this window — the job keeps running.")
        self.log("[*] Re-open the app anytime to see progress.")
        notify("Transform Studio", f"Worker started (PID {proc.pid}). Runs until finished.")
        self._refresh_status()
        if self.bg_var.get():
            self.root.iconify()

    def _stop_run(self):
        pid = get_running_pid()
        if not pid:
            self.log("[*] No worker running.")
            # still mark state stopped
            st = load_state()
            if st and st.get("status") == "running":
                st["status"] = "stopped"
                save_state(st)
            self._refresh_status()
            return
        try:
            os.kill(pid, signal.SIGTERM)
            self.log(f"[*] Sent SIGTERM to PID {pid}")
            notify("Transform Studio", "Stop requested — worker will save progress.")
        except ProcessLookupError:
            set_running(False)
            self.log("[*] Process already gone.")
        self.root.after(2000, self._refresh_status)

    def _on_close(self):
        if is_running():
            if messagebox.askyesno(
                "Quit GUI",
                "A background worker is still running.\n\n"
                "Yes = close this window only (job continues)\n"
                "No = stay open",
            ):
                self.root.destroy()
            # else stay
        else:
            self.root.destroy()


def main():
    # headless? (shouldn't reach here for worker)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

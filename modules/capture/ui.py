"""
Futuristic capture UI — live steps, timers, AP list, clients, handshake status.
"""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext

from .engine import CaptureEngine


BG = "#0a0e17"
PANEL = "#111827"
ACCENT = "#00e5a8"
ACCENT2 = "#3b82f6"
WARN = "#f59e0b"
ERR = "#ef4444"
TEXT = "#e5e7eb"
DIM = "#6b7280"
OK = "#22c55e"


class CaptureWindow:
    def __init__(self, parent=None, on_handshake=None):
        self.on_handshake = on_handshake  # callback(path) when capture succeeds
        self.win = tk.Toplevel(parent) if parent else tk.Tk()
        self.win.title("Handshake Capture — Transform Studio")
        self.win.geometry("980x720")
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self.engine: CaptureEngine | None = None
        self._worker: threading.Thread | None = None
        self._aps: list = []
        self._selected_ap = None
        self._step_t0 = None

        self.iface_var = tk.StringVar(value="wlan1")
        self.outdir_var = tk.StringVar(value="/home/kali/transform_engine/handshake")
        self.scan_var = tk.IntVar(value=20)
        self.deauth_var = tk.IntVar(value=1)
        self.deauth_delay_var = tk.IntVar(value=8)
        self.interval_var = tk.StringVar(value="60")
        self.selected_client = tk.StringVar(value="")
        self._client_macs: list = []

        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self.win, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(
            hdr, text="◈  HANDSHAKE CAPTURE",
            font=("Consolas", 18, "bold"), fg=ACCENT, bg=BG,
        ).pack(side="left")
        self.clock_lbl = tk.Label(hdr, text="", font=("Consolas", 11), fg=DIM, bg=BG)
        self.clock_lbl.pack(side="right")
        self._tick_clock()

        # Config bar
        cfg = tk.Frame(self.win, bg=PANEL, highlightbackground="#1f2937", highlightthickness=1)
        cfg.pack(fill="x", padx=16, pady=6)
        inner = tk.Frame(cfg, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=8)

        def lbl(t):
            return tk.Label(inner, text=t, fg=DIM, bg=PANEL, font=("Consolas", 9))

        lbl("IFACE").grid(row=0, column=0, sticky="w")
        tk.Entry(inner, textvariable=self.iface_var, width=10, bg="#0f172a", fg=TEXT,
                 insertbackground=TEXT, relief="flat").grid(row=0, column=1, padx=6)
        lbl("OUT DIR").grid(row=0, column=2, sticky="w", padx=(12, 0))
        tk.Entry(inner, textvariable=self.outdir_var, width=28, bg="#0f172a", fg=TEXT,
                 insertbackground=TEXT, relief="flat").grid(row=0, column=3, padx=6)
        lbl("SCAN s").grid(row=0, column=4, sticky="w", padx=(12, 0))
        tk.Spinbox(inner, from_=5, to=120, textvariable=self.scan_var, width=5,
                   bg="#0f172a", fg=TEXT, buttonbackground=PANEL).grid(row=0, column=5, padx=6)
        lbl("FRAMES").grid(row=0, column=6, sticky="w", padx=(12, 0))
        tk.Spinbox(inner, from_=1, to=10, textvariable=self.deauth_var, width=4,
                   bg="#0f172a", fg=TEXT, buttonbackground=PANEL).grid(row=0, column=7, padx=4)
        lbl("EVERY").grid(row=0, column=8, sticky="w", padx=(10, 0))
        ttk.Combobox(
            inner, textvariable=self.interval_var, width=8, state="readonly",
            values=("30", "60", "120"),
        ).grid(row=0, column=9, padx=4)
        tk.Label(inner, text="sec", fg=DIM, bg=PANEL, font=("Consolas", 9)).grid(row=0, column=10)
        lbl("DELAY").grid(row=0, column=11, sticky="w", padx=(10, 0))
        tk.Spinbox(inner, from_=0, to=60, textvariable=self.deauth_delay_var, width=4,
                   bg="#0f172a", fg=TEXT, buttonbackground=PANEL).grid(row=0, column=12, padx=4)

        # Steps progress
        steps_f = tk.Frame(self.win, bg=BG)
        steps_f.pack(fill="x", padx=16, pady=4)
        self.step_labels = []
        names = ["1 KILL", "2 MONITOR", "3 SCAN", "4 CAPTURE"]
        for i, name in enumerate(names):
            lb = tk.Label(
                steps_f, text=name, font=("Consolas", 10, "bold"),
                fg=DIM, bg="#0f172a", padx=14, pady=6,
            )
            lb.pack(side="left", padx=4)
            self.step_labels.append(lb)
        self.step_time_lbl = tk.Label(steps_f, text="", font=("Consolas", 10), fg=ACCENT2, bg=BG)
        self.step_time_lbl.pack(side="right", padx=8)

        # Main split
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=6)

        # Left: networks + clients
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(left, text="NETWORKS", font=("Consolas", 10, "bold"), fg=ACCENT2, bg=BG).pack(anchor="w")
        cols = ("#", "ESSID", "BSSID", "CH", "PWR", "ENC")
        self.ap_tree = ttk.Treeview(left, columns=cols, show="headings", height=10)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Treeview",
            background="#0f172a", foreground=TEXT, fieldbackground="#0f172a",
            rowheight=24, font=("Consolas", 9),
        )
        style.configure("Treeview.Heading", background=PANEL, foreground=ACCENT, font=("Consolas", 9, "bold"))
        style.map("Treeview", background=[("selected", "#1e3a5f")])
        for c, w in zip(cols, (36, 140, 140, 40, 48, 70)):
            self.ap_tree.heading(c, text=c)
            self.ap_tree.column(c, width=w, anchor="w")
        self.ap_tree.pack(fill="both", expand=True, pady=4)
        self.ap_tree.bind("<<TreeviewSelect>>", self._on_select_ap)

        tk.Label(left, text="CLIENTS — click one to target (1 deauth per interval)",
                 font=("Consolas", 10, "bold"), fg=WARN, bg=BG).pack(anchor="w", pady=(8, 0))
        self.client_list = tk.Listbox(
            left, height=6, bg="#0f172a", fg=TEXT, font=("Consolas", 9),
            selectbackground="#1e3a5f", selectforeground=ACCENT,
            relief="flat", highlightthickness=0,
        )
        self.client_list.pack(fill="x", pady=4)
        self.client_list.bind("<<ListboxSelect>>", self._on_select_client)
        self.client_target_lbl = tk.Label(
            left, text="Target: (auto = first client seen)",
            font=("Consolas", 9), fg=DIM, bg=BG, anchor="w",
        )
        self.client_target_lbl.pack(fill="x")

        # Right: status + log
        right = tk.Frame(body, bg=BG, width=340)
        right.pack(side="right", fill="both", padx=(8, 0))
        right.pack_propagate(False)

        self.status_panel = tk.Label(
            right,
            text="IDLE\n\nLoad interface & start scan",
            font=("Consolas", 11), fg=TEXT, bg=PANEL,
            justify="left", anchor="nw", padx=12, pady=12,
        )
        self.status_panel.pack(fill="x", pady=(0, 8))

        self.hs_indicator = tk.Label(
            right, text="○  NO HANDSHAKE", font=("Consolas", 14, "bold"),
            fg=DIM, bg="#0f172a", pady=12,
        )
        self.hs_indicator.pack(fill="x", pady=4)

        # 4-way message indicators
        msgf = tk.Frame(right, bg="#0f172a")
        msgf.pack(fill="x", pady=6)
        tk.Label(msgf, text="4-WAY EAPOL", font=("Consolas", 9, "bold"),
                 fg=ACCENT2, bg="#0f172a").pack(anchor="w", padx=8, pady=(6, 2))
        row = tk.Frame(msgf, bg="#0f172a")
        row.pack(fill="x", padx=8, pady=(0, 8))
        self.msg_labels = {}
        for name in ("M1", "M2", "M3", "M4"):
            lb = tk.Label(
                row, text=f"○ {name}", font=("Consolas", 12, "bold"),
                fg=DIM, bg="#111827", padx=10, pady=8,
            )
            lb.pack(side="left", padx=4, expand=True, fill="x")
            self.msg_labels[name] = lb

        tk.Label(right, text="EVENT LOG", font=("Consolas", 10, "bold"), fg=ACCENT2, bg=BG).pack(anchor="w")
        self.log_box = scrolledtext.ScrolledText(
            right, bg="#05080f", fg=ACCENT, font=("Consolas", 9),
            insertbackground=ACCENT, relief="flat", height=18,
        )
        self.log_box.pack(fill="both", expand=True, pady=4)

        # Buttons
        btnf = tk.Frame(self.win, bg=BG)
        btnf.pack(fill="x", padx=16, pady=10)

        def mkbtn(text, cmd, color=ACCENT2):
            b = tk.Button(
                btnf, text=text, command=cmd, font=("Consolas", 10, "bold"),
                bg=color, fg="#0a0e17", activebackground=ACCENT, relief="flat",
                padx=14, pady=8, cursor="hand2",
            )
            b.pack(side="left", padx=4)
            return b

        self.btn_scan = mkbtn("▶  SCAN", self._start_scan, ACCENT2)
        self.btn_cap = mkbtn("⚡  CAPTURE", self._start_capture, WARN)
        self.btn_stop = mkbtn("■  STOP", self._stop, ERR)
        self.btn_cap.config(state=tk.DISABLED)

        tk.Label(
            btnf,
            text="Legal: only networks you own or have written permission to test.",
            font=("Consolas", 8), fg=DIM, bg=BG,
        ).pack(side="right", padx=8)

    def _tick_clock(self):
        self.clock_lbl.config(text=time.strftime("%H:%M:%S"))
        self.win.after(1000, self._tick_clock)

    def _ui(self, fn):
        self.win.after(0, fn)

    def _log(self, msg, level="info"):
        colors = {"info": ACCENT, "ok": OK, "error": ERR, "warn": WARN}
        tag = level

        def do():
            self.log_box.tag_configure(tag, foreground=colors.get(level, ACCENT))
            ts = time.strftime("%H:%M:%S")
            self.log_box.insert(tk.END, f"[{ts}] {msg}\n", tag)
            self.log_box.see(tk.END)

        self._ui(do)

    def _set_step(self, index: int, active=True):
        def do():
            for i, lb in enumerate(self.step_labels):
                if i + 1 < index:
                    lb.config(fg=OK, bg="#052e1a")
                elif i + 1 == index and active:
                    lb.config(fg="#0a0e17", bg=ACCENT)
                elif i + 1 == index:
                    lb.config(fg=OK, bg="#052e1a")
                else:
                    lb.config(fg=DIM, bg="#0f172a")

        self._ui(do)

    def _on_event(self, kind: str, data: dict):
        if kind == "log":
            self._log(data.get("msg", ""), data.get("level", "info"))
        elif kind == "step":
            self._step_t0 = time.time()
            idx = data.get("index", 1)
            self._set_step(idx, active=True)
            self._log(f"── Step {idx}: {data.get('name')} ──")
            self._ui(lambda: self.step_time_lbl.config(text="…"))
        elif kind == "step_done":
            sec = data.get("seconds", 0)
            self._log(f"Step done in {sec:.1f}s — {data.get('name')}", "ok")
            self._ui(lambda: self.step_time_lbl.config(text=f"{sec:.1f}s"))
        elif kind == "scan_tick":
            rem = data.get("remaining", 0)
            n = data.get("count", 0)

            def do():
                self.status_panel.config(
                    text=f"SCANNING\n\n{rem}s remaining\n{n} networks found"
                )

            self._ui(do)
        elif kind == "aps":
            self._aps = data.get("aps", [])
            self._ui(self._refresh_aps)
        elif kind == "capture_status":
            self._ui(lambda: self._update_capture(data))
        elif kind == "done":
            ok = data.get("handshake")
            path = data.get("path", "")
            msgs = data.get("messages") or {}

            def do():
                for name in ("M1", "M2", "M3", "M4"):
                    got = bool(msgs.get(name))
                    lb = self.msg_labels.get(name)
                    if lb:
                        lb.config(
                            text=f"{'●' if got else '○'} {name}",
                            fg=OK if got else DIM,
                            bg="#052e1a" if got else "#111827",
                        )
                if ok:
                    got = [m for m in ("M1", "M2", "M3", "M4") if msgs.get(m)]
                    self.hs_indicator.config(text="●  SUCCESS — I GOT THEM", fg=OK)
                    self.status_panel.config(
                        text=f"SUCCESS — handshake captured\n\n"
                             f"Messages: {', '.join(got) or 'detected'}\n\n"
                             f"{path}\n\nReady for transform engine."
                    )
                    self._log(f"SUCCESS — I got them: {', '.join(got)}", "ok")
                    self._log(f"Saved: {path}", "ok")
                    if self.on_handshake and path:
                        self.on_handshake(path)
                else:
                    self.hs_indicator.config(text="○  NO HANDSHAKE", fg=ERR)
                    self.status_panel.config(text=f"FINISHED — no handshake\n\n{path}")

            self._ui(do)
        elif kind == "monitor":
            self._log(f"Monitor iface: {data.get('iface')}", "ok")

    def _refresh_aps(self):
        self.ap_tree.delete(*self.ap_tree.get_children())
        for i, ap in enumerate(sorted(self._aps, key=lambda a: a["essid"]), 1):
            self.ap_tree.insert(
                "", "end",
                values=(i, ap["essid"], ap["bssid"], ap["channel"], ap["power"], ap["privacy"]),
            )

    def _on_select_ap(self, _evt=None):
        sel = self.ap_tree.selection()
        if not sel:
            return
        vals = self.ap_tree.item(sel[0], "values")
        idx = int(vals[0]) - 1
        if 0 <= idx < len(self._aps):
            # match by sorted order used in refresh
            sorted_aps = sorted(self._aps, key=lambda a: a["essid"])
            self._selected_ap = sorted_aps[idx]
            self.btn_cap.config(state=tk.NORMAL)
            self.status_panel.config(
                text=f"TARGET SELECTED\n\n{self._selected_ap['essid']}\n"
                     f"{self._selected_ap['bssid']}\nch {self._selected_ap['channel']}"
            )

    def _update_capture(self, data: dict):
        clients = data.get("clients") or []
        attempt = data.get("attempt", 0)
        hs = data.get("handshake")
        elapsed = data.get("elapsed", 0)
        ap = data.get("ap") or {}
        msgs = data.get("messages") or {}
        deauth_active = data.get("deauth_active", False)
        countdown = data.get("deauth_countdown", 0)

        # refresh client list (keep selection if still present)
        prev = self.selected_client.get()
        self._client_macs = [c["station"] for c in clients]
        self.client_list.delete(0, tk.END)
        if clients:
            for c in clients:
                self.client_list.insert(
                    tk.END,
                    f"{c['station']}  pwr={c.get('power','')}  {c.get('probed','')}",
                )
            if prev and prev in self._client_macs:
                idx = self._client_macs.index(prev)
                self.client_list.selection_set(idx)
                self.client_target_lbl.config(
                    text=f"Target: {prev}", fg=ACCENT
                )
            elif not prev:
                self.client_target_lbl.config(
                    text="Target: (auto = first client)", fg=DIM
                )
        else:
            self.client_list.insert(tk.END, "… no clients yet")

        # Update M1–M4 lights
        for name in ("M1", "M2", "M3", "M4"):
            got = bool(msgs.get(name))
            lb = self.msg_labels.get(name)
            if lb:
                if got:
                    lb.config(text=f"● {name}", fg=OK, bg="#052e1a")
                else:
                    lb.config(text=f"○ {name}", fg=DIM, bg="#111827")

        if hs:
            self.hs_indicator.config(text="●  SUCCESS — GOT HANDSHAKE", fg=OK)
        elif not deauth_active:
            self.hs_indicator.config(
                text=f"◎  LISTENING  deauth in {countdown:.0f}s",
                fg=ACCENT2,
            )
        else:
            self.hs_indicator.config(
                text=f"○  CAPTURING  deauth #{attempt}",
                fg=WARN,
            )

        got_list = [m for m in ("M1", "M2", "M3", "M4") if msgs.get(m)]
        eapol_n = data.get("eapol_count", 0)
        phase = "DEAUTH ACTIVE" if deauth_active else f"LISTEN ({countdown:.0f}s left)"
        self.status_panel.config(
            text=f"CAPTURE LIVE — {phase}\n\n"
                 f"Target: {ap.get('essid', '')}\n"
                 f"Round: {attempt}\n"
                 f"Clients: {len(clients)}\n"
                 f"Elapsed: {elapsed:.0f}s\n"
                 f"EAPOL frames: {eapol_n}\n"
                 f"Seen: {', '.join(got_list) if got_list else 'none yet'}\n"
                 f"Handshake: {'SUCCESS' if hs else 'pending'}"
        )

    def _on_select_client(self, _evt=None):
        sel = self.client_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._client_macs):
            mac = self._client_macs[idx]
            self.selected_client.set(mac)
            self.client_target_lbl.config(text=f"Target: {mac}", fg=ACCENT)
            self._log(f"Deauth target set: {mac}", "ok")

    def _make_engine(self) -> CaptureEngine:
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            interval = 60.0
        return CaptureEngine(
            phy_iface=self.iface_var.get().strip() or "wlan1",
            out_dir=self.outdir_var.get().strip() or "/home/kali/transform_engine/handshake",
            deauth_count=int(self.deauth_var.get()),
            scan_time=int(self.scan_var.get()),
            deauth_delay=float(self.deauth_delay_var.get()),
            deauth_interval=interval,
            target_client=self.selected_client.get().strip() or None,
            on_event=self._on_event,
        )

    def _start_scan(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Busy", "A job is already running. Stop it first.")
            return
        eng = self._make_engine()
        if not eng.can_elevate():
            messagebox.showerror(
                "Privileges required",
                "Capture needs root for monitor mode / deauth.\n\n"
                "Fix: re-run the installer so passwordless sudo is set up:\n"
                "  sudo bash install.sh\n\n"
                "Or launch once with:  sudo ./launch.sh",
            )
            return
        missing = eng.check_tools()
        if missing:
            messagebox.showerror("Missing tools", f"Install: {', '.join(missing)}\nsudo apt install aircrack-ng")
            return

        self.engine = eng
        self.btn_scan.config(state=tk.DISABLED)
        self.btn_cap.config(state=tk.DISABLED)

        def job():
            try:
                eng.kill_interfering()
                eng.start_monitor()
                aps = eng.scan_networks()
                if not aps:
                    self._log("No networks found", "warn")
                else:
                    self._log(f"Found {len(aps)} networks — select one and click CAPTURE", "ok")

                def enable():
                    self.btn_scan.config(state=tk.NORMAL)
                    if self._aps:
                        self.btn_cap.config(state=tk.NORMAL)

                self._ui(enable)
            except Exception as e:
                self._log(str(e), "error")
                self._ui(lambda: self.btn_scan.config(state=tk.NORMAL))

        self._worker = threading.Thread(target=job, daemon=True)
        self._worker.start()

    def _start_capture(self):
        if not self._selected_ap:
            messagebox.showwarning("Select", "Select a network from the list first.")
            return
        if not self.engine:
            self.engine = self._make_engine()
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Busy", "Wait for current job or press STOP.")
            return

        ap = self._selected_ap
        eng = self.engine
        self.btn_cap.config(state=tk.DISABLED)
        self.btn_scan.config(state=tk.DISABLED)

        def job():
            try:
                eng.capture_handshake(ap)
            except Exception as e:
                self._log(str(e), "error")
            finally:
                try:
                    eng.cleanup()
                except Exception:
                    pass
                self._ui(lambda: (
                    self.btn_scan.config(state=tk.NORMAL),
                    self.btn_cap.config(state=tk.NORMAL),
                ))

        self._worker = threading.Thread(target=job, daemon=True)
        self._worker.start()

    def _stop(self):
        if self.engine:
            self.engine.stop()
            self._log("Stop requested…", "warn")

    def _on_close(self):
        if self.engine:
            self.engine.stop()
        self.win.destroy()


def open_capture_window(parent=None, on_handshake=None):
    return CaptureWindow(parent=parent, on_handshake=on_handshake)

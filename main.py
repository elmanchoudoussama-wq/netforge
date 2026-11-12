#!/usr/bin/env python3
"""
NetForge — Unified network lab toolkit
Portal · Capture · Transform · Analyzer
Futuristic dark GUI, desktop-ready, minimal friction.
"""
from __future__ import annotations

import os
import sys
import threading
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules"))

# ── palette ────────────────────────────────────────────────────────────────
BG       = "#0a0e17"
PANEL    = "#111827"
PANEL2   = "#0f172a"
BORDER   = "#1f2937"
ACCENT   = "#00e5a8"
ACCENT2  = "#3b82f6"
TEXT     = "#e5e7eb"
DIM      = "#6b7280"
OK       = "#22c55e"
WARN     = "#f59e0b"
ERR      = "#ef4444"
FONT     = ("Segoe UI", 10)
FONT_B   = ("Segoe UI", 10, "bold")
FONT_H   = ("Segoe UI", 18, "bold")
FONT_M   = ("Consolas", 10)


class NetForgeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NetForge")
        self.root.geometry("980x720")
        self.root.minsize(860, 620)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_style()
        self._build_shell()
        self._show_portal()          # default tab

    # ── style ──────────────────────────────────────────────────────────────
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL2)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Dim.TLabel", background=BG, foreground=DIM, font=FONT)
        style.configure("Accent.TLabel", background=BG, foreground=ACCENT, font=FONT_B)
        style.configure("Header.TLabel", background=BG, foreground=ACCENT, font=FONT_H)
        style.configure("TButton", font=FONT, padding=8)
        style.configure("Accent.TButton", font=FONT_B)
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=FONT)
        style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=DIM, padding=[16, 8], font=FONT_B)
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL2)],
                  foreground=[("selected", ACCENT)])

    # ── shell ──────────────────────────────────────────────────────────────
    def _build_shell(self):
        # top bar
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=20, pady=(16, 8))

        tk.Label(top, text="◈  NETFORGE", font=FONT_H, fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(top, text="  network lab toolkit", font=FONT, fg=DIM, bg=BG).pack(side="left", padx=(4, 0))

        # nav
        nav = tk.Frame(self.root, bg=BG)
        nav.pack(fill="x", padx=20, pady=(0, 10))

        self.nav_btns = {}
        for key, label in [
            ("portal", "Portal"),
            ("capture", "Capture"),
            ("transform", "Transform"),
            ("analyzer", "Analyzer"),
        ]:
            b = tk.Button(
                nav, text=label, font=FONT_B, bg=PANEL, fg=DIM,
                activebackground=PANEL2, activeforeground=ACCENT,
                relief="flat", bd=0, padx=18, pady=8, cursor="hand2",
                command=lambda k=key: self._switch(k),
            )
            b.pack(side="left", padx=(0, 6))
            self.nav_btns[key] = b

        # content area
        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.pages = {}
        self.current = None

    def _switch(self, key: str):
        for k, b in self.nav_btns.items():
            if k == key:
                b.configure(bg=PANEL2, fg=ACCENT)
            else:
                b.configure(bg=PANEL, fg=DIM)

        if self.current:
            self.pages[self.current].pack_forget()

        if key not in self.pages:
            builders = {
                "portal": self._build_portal_page,
                "capture": self._build_capture_page,
                "transform": self._build_transform_page,
                "analyzer": self._build_analyzer_page,
            }
            self.pages[key] = builders[key]()

        self.pages[key].pack(fill="both", expand=True)
        self.current = key

    def _show_portal(self):
        self._switch("portal")

    # ── helpers ────────────────────────────────────────────────────────────
    def _card(self, parent, title: str = "") -> tk.Frame:
        outer = tk.Frame(parent, bg=BORDER, bd=0)
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        if title:
            tk.Label(inner, text=title, font=FONT_B, fg=ACCENT, bg=PANEL).pack(
                anchor="w", padx=14, pady=(12, 4)
            )
        return outer, inner

    def _btn(self, parent, text, cmd, primary=False, **kw):
        bg = ACCENT if primary else PANEL2
        fg = "#0a0e17" if primary else TEXT
        return tk.Button(
            parent, text=text, command=cmd, font=FONT_B,
            bg=bg, fg=fg, activebackground=ACCENT2, activeforeground="#fff",
            relief="flat", bd=0, padx=16, pady=8, cursor="hand2", **kw
        )

    def _entry(self, parent, var, width=28, show=None):
        e = tk.Entry(
            parent, textvariable=var, width=width, font=FONT,
            bg=PANEL2, fg=TEXT, insertbackground=TEXT,
            relief="flat", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
        )
        if show:
            e.configure(show=show)
        return e

    def _log_box(self, parent, height=12):
        t = scrolledtext.ScrolledText(
            parent, height=height, font=FONT_M,
            bg="#070b12", fg="#7dd3a0", insertbackground=TEXT,
            relief="flat", bd=0,
        )
        return t

    # ══════════════════════════════════════════════════════════════════════
    # PORTAL PAGE
    # ══════════════════════════════════════════════════════════════════════
    def _build_portal_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)

        # settings card
        card, body = self._card(page, "PORTAL SETTINGS")
        card.pack(fill="x", pady=(0, 10))

        grid = tk.Frame(body, bg=PANEL)
        grid.pack(fill="x", padx=14, pady=(0, 12))

        self.p_ssid = tk.StringVar(value="FreeWiFi")
        self.p_pass = tk.StringVar(value="1234")
        self.p_tries = tk.StringVar(value="1")
        self.p_mode = tk.StringVar(value="bluetooth")
        self.p_iface = tk.StringVar(value="")

        tk.Label(grid, text="SSID", fg=DIM, bg=PANEL, font=FONT).grid(row=0, column=0, sticky="w", pady=4)
        self._entry(grid, self.p_ssid).grid(row=0, column=1, sticky="w", padx=8)

        tk.Label(grid, text="Password", fg=DIM, bg=PANEL, font=FONT).grid(row=1, column=0, sticky="w", pady=4)
        self._entry(grid, self.p_pass, show="•").grid(row=1, column=1, sticky="w", padx=8)

        tk.Label(grid, text="Max tries", fg=DIM, bg=PANEL, font=FONT).grid(row=2, column=0, sticky="w", pady=4)
        tk.Spinbox(grid, from_=1, to=10, textvariable=self.p_tries, width=5,
                   bg=PANEL2, fg=TEXT, buttonbackground=PANEL).grid(row=2, column=1, sticky="w", padx=8)

        # source
        src, sbody = self._card(page, "INTERNET SOURCE")
        src.pack(fill="x", pady=(0, 10))

        modes = [
            ("Bluetooth (phone)", "bluetooth"),
            ("Existing interface (auto)", "existing"),
            ("Manual interface", "manual"),
            ("Offline (test only)", "offline"),
        ]
        for text, val in modes:
            tk.Radiobutton(
                sbody, text=text, variable=self.p_mode, value=val,
                bg=PANEL, fg=TEXT, selectcolor=PANEL2,
                activebackground=PANEL, activeforeground=ACCENT,
                font=FONT, command=self._portal_toggle_manual,
            ).pack(anchor="w", padx=14, pady=2)

        self.p_manual_frame = tk.Frame(sbody, bg=PANEL)
        tk.Label(self.p_manual_frame, text="Interface", fg=DIM, bg=PANEL, font=FONT).pack(side="left")
        self._entry(self.p_manual_frame, self.p_iface, width=16).pack(side="left", padx=8)

        # status + actions
        act = tk.Frame(page, bg=BG)
        act.pack(fill="x", pady=6)

        self.p_status = tk.Label(act, text="● Stopped", font=FONT_B, fg=ERR, bg=BG)
        self.p_status.pack(side="left")

        bf = tk.Frame(act, bg=BG)
        bf.pack(side="right")
        self.p_btn_start = self._btn(bf, "▶  Start", self._portal_start, primary=True)
        self.p_btn_start.pack(side="left", padx=4)
        self.p_btn_stop = self._btn(bf, "■  Stop", self._portal_stop)
        self.p_btn_stop.pack(side="left", padx=4)
        self._btn(bf, "Status", self._portal_status).pack(side="left", padx=4)
        self._btn(bf, "Forget All", self._portal_forget).pack(side="left", padx=4)

        # log
        logc, logb = self._card(page, "LIVE LOG")
        logc.pack(fill="both", expand=True, pady=(8, 0))
        self.p_log = self._log_box(logb, height=14)
        self.p_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._portal_poll()
        return page

    def _portal_toggle_manual(self):
        if self.p_mode.get() == "manual":
            self.p_manual_frame.pack(anchor="w", padx=14, pady=6)
        else:
            self.p_manual_frame.pack_forget()

    def _portal_append(self, text: str):
        self.p_log.configure(state="normal")
        self.p_log.insert("end", text.rstrip() + "\n")
        self.p_log.see("end")
        self.p_log.configure(state="disabled")

    def _portal_start(self):
        self.p_btn_start.configure(state="disabled")
        self.p_status.configure(text="● Starting…", fg=WARN)

        def task():
            helper = "/usr/local/lib/netforge/portal-helper"
            script = ROOT / "modules" / "portal" / "portal.sh"
            env = {
                **os.environ,
                "NF_SSID": self.p_ssid.get().strip() or "FreeWiFi",
                "NF_PASS": self.p_pass.get().strip() or "1234",
                "NF_TRIES": self.p_tries.get(),
                "NF_MODE": self.p_mode.get(),
                "NF_IFACE": self.p_iface.get().strip(),
            }
            try:
                if Path(helper).is_file():
                    # write env for helper (read by portal-helper as root)
                    env_file = Path("/tmp/netforge-portal.env")
                    env_file.write_text(
                        f'NF_SSID="{env["NF_SSID"]}"\n'
                        f'NF_PASS="{env["NF_PASS"]}"\n'
                        f'NF_TRIES="{env["NF_TRIES"]}"\n'
                        f'NF_MODE="{env["NF_MODE"]}"\n'
                        f'NF_IFACE="{env["NF_IFACE"]}"\n'
                    )
                    r = subprocess.run(
                        ["sudo", "-n", helper, "start"],
                        capture_output=True, text=True, timeout=120,
                    )
                else:
                    r = subprocess.run(
                        ["sudo", "-n", "bash", str(script), "start"],
                        capture_output=True, text=True, env=env, timeout=120,
                    )
                out = (r.stdout or "") + (r.stderr or "")
                ok = r.returncode == 0
            except Exception as e:
                out = str(e)
                ok = False
            self.root.after(0, lambda: self._portal_after_start(ok, out))

        threading.Thread(target=task, daemon=True).start()

    def _portal_after_start(self, ok: bool, out: str):
        self._portal_append(out)
        if ok:
            self.p_status.configure(text="● Running", fg=OK)
            self.p_btn_stop.configure(state="normal")
        else:
            self.p_status.configure(text="● Failed", fg=ERR)
            self.p_btn_start.configure(state="normal")
            messagebox.showerror("Portal", "Start failed — see log")

    def _portal_stop(self):
        self.p_btn_stop.configure(state="disabled")
        self.p_status.configure(text="● Stopping…", fg=WARN)

        def task():
            helper = "/usr/local/lib/netforge/portal-helper"
            script = ROOT / "modules" / "portal" / "portal.sh"
            try:
                if Path(helper).is_file():
                    r = subprocess.run(["sudo", "-n", helper, "stop"], capture_output=True, text=True, timeout=30)
                else:
                    r = subprocess.run(
                        ["sudo", "-n", "bash", str(script), "stop"],
                        capture_output=True, text=True, timeout=30,
                    )
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as e:
                out = str(e)
            self.root.after(0, lambda: self._portal_after_stop(out))

        threading.Thread(target=task, daemon=True).start()

    def _portal_after_stop(self, out: str):
        self._portal_append(out)
        self.p_status.configure(text="● Stopped", fg=ERR)
        self.p_btn_start.configure(state="normal")
        self.p_btn_stop.configure(state="disabled")

    def _portal_status(self):
        def task():
            helper = "/usr/local/lib/netforge/portal-helper"
            script = ROOT / "modules" / "portal" / "portal.sh"
            try:
                if Path(helper).is_file():
                    r = subprocess.run(["sudo", "-n", helper, "status"], capture_output=True, text=True, timeout=10)
                else:
                    r = subprocess.run(
                        ["sudo", "-n", "bash", str(script), "status"],
                        capture_output=True, text=True, timeout=10,
                    )
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as e:
                out = str(e)
            self.root.after(0, lambda: self._portal_append(out or "(empty)"))
        threading.Thread(target=task, daemon=True).start()

    def _portal_forget(self):
        if not messagebox.askyesno("Forget", "Forget all authenticated devices?"):
            return
        def task():
            helper = "/usr/local/lib/netforge/portal-helper"
            script = ROOT / "modules" / "portal" / "portal.sh"
            try:
                if Path(helper).is_file():
                    r = subprocess.run(["sudo", "-n", helper, "forget", "all"], capture_output=True, text=True)
                else:
                    r = subprocess.run(
                        ["sudo", "-n", "bash", str(script), "forget", "all"],
                        capture_output=True, text=True,
                    )
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as e:
                out = str(e)
            self.root.after(0, lambda: self._portal_append(out))
        threading.Thread(target=task, daemon=True).start()

    def _portal_poll(self):
        try:
            r = subprocess.run(["pgrep", "-f", "nds-verify.py"], capture_output=True)
            running = r.returncode == 0
            if running:
                self.p_status.configure(text="● Running", fg=OK)
                self.p_btn_start.configure(state="disabled")
                self.p_btn_stop.configure(state="normal")
            else:
                if self.p_status.cget("text") not in ("● Starting…", "● Stopping…"):
                    self.p_status.configure(text="● Stopped", fg=ERR)
                    self.p_btn_start.configure(state="normal")
                    self.p_btn_stop.configure(state="disabled")
        except Exception:
            pass

        # Stream new auth-log lines into LIVE LOG (ALLOW / DENY)
        try:
            self._portal_stream_auth_log()
        except Exception:
            pass

        self.root.after(2000, self._portal_poll)

    def _portal_stream_auth_log(self):
        """Append only new lines from the auth log (world-readable after install)."""
        if not hasattr(self, "_auth_log_pos"):
            self._auth_log_pos = 0
            self._auth_log_inode = None
            self._auth_perm_warned = False

        auth_path = Path("/var/log/bt-portal-auth.log")
        chunk = ""

        try:
            st = auth_path.stat()
            inode = st.st_ino
            size = st.st_size
            if self._auth_log_inode is not None and inode != self._auth_log_inode:
                self._auth_log_pos = 0
            if size < self._auth_log_pos:
                self._auth_log_pos = 0
            self._auth_log_inode = inode

            with open(auth_path, "r", errors="replace") as f:
                f.seek(self._auth_log_pos)
                chunk = f.read()
                self._auth_log_pos = f.tell()
        except PermissionError:
            if not self._auth_perm_warned:
                self._auth_perm_warned = True
                self._portal_append(
                    "!! auth log not readable (need 644). Fix once:\n"
                    "   sudo chmod 644 /var/log/bt-portal-auth.log"
                )
            return
        except FileNotFoundError:
            return
        except Exception:
            return

        if chunk.strip():
            self._portal_append(chunk)

    def _build_capture_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)
        card, body = self._card(page, "HANDSHAKE CAPTURE")
        card.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Open the full capture interface (monitor mode, AP scan, deauth, .cap output).",
            fg=DIM, bg=PANEL, font=FONT, wraplength=700, justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 12))

        self._btn(body, "Open Capture Window", self._open_capture, primary=True).pack(
            anchor="w", padx=16, pady=8
        )

        tk.Label(
            body,
            text="Requires aircrack-ng and a Wi-Fi card that supports monitor mode.\n"
                 "Privileged actions use the installed helper (no password after install).",
            fg=DIM, bg=PANEL, font=FONT, justify="left",
        ).pack(anchor="w", padx=16, pady=12)

        return page

    def _open_capture(self):
        try:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            if str(ROOT / "modules") not in sys.path:
                sys.path.insert(0, str(ROOT / "modules"))
            from modules.capture.ui import CaptureWindow
            CaptureWindow(parent=self.root)
        except Exception as e:
            messagebox.showerror("Capture", f"Could not open capture UI:\n{e}")

    # ══════════════════════════════════════════════════════════════════════
    # TRANSFORM PAGE (simplified entry + launch full studio)
    # ══════════════════════════════════════════════════════════════════════
    def _build_transform_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)
        card, body = self._card(page, "TRANSFORM ENGINE")
        card.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="GPU/CPU accelerated WPA key recovery with background worker and auto-resume.",
            fg=DIM, bg=PANEL, font=FONT, wraplength=700, justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 12))

        self._btn(body, "Open Transform Studio", self._open_transform, primary=True).pack(
            anchor="w", padx=16, pady=8
        )

        tk.Label(
            body,
            text="Supports numeric sequences, wordlists, OpenCL devices, progress persistence,\n"
                 "and systemd user service for resume after reboot.",
            fg=DIM, bg=PANEL, font=FONT, justify="left",
        ).pack(anchor="w", padx=16, pady=12)

        return page

    def _open_transform(self):
        app_py = ROOT / "modules" / "transform" / "studio.py"
        if not app_py.exists():
            messagebox.showerror("Transform", f"Studio not found:\n{app_py}")
            return
        py = sys.executable
        for cand in (ROOT / "venv" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
            if cand.is_file():
                py = str(cand)
                break
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(ROOT / "modules")
        try:
            subprocess.Popen(
                [py, str(app_py)],
                cwd=str(ROOT),
                env=env,
            )
        except Exception as e:
            messagebox.showerror("Transform", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # ANALYZER PAGE
    # ══════════════════════════════════════════════════════════════════════
    def _build_analyzer_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)
        card, body = self._card(page, "LAB HTTP ANALYZER")
        card.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Closed-lab HTTP traffic analyzer (passive sniff, ARP lab capture, log parse, live probe).\n"
                 "For isolated lab networks you own only.",
            fg=DIM, bg=PANEL, font=FONT, wraplength=700, justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 12))

        self._btn(body, "Open Analyzer", self._open_analyzer, primary=True).pack(
            anchor="w", padx=16, pady=8
        )
        return page

    def _open_analyzer(self):
        try:
            path = ROOT / "modules" / "analyzer" / "http_analyzer.py"
            subprocess.Popen([sys.executable, str(path)], cwd=str(ROOT))
        except Exception as e:
            messagebox.showerror("Analyzer", str(e))

    # ── close ──────────────────────────────────────────────────────────────
    def _on_close(self):
        self.root.destroy()


def main():
    root = tk.Tk()
    # try to set a nice icon if present
    icon = ROOT / "assets" / "icon.svg"
    try:
        if icon.exists():
            # Tk on Linux often prefers .png/.xbm; skip if fails
            pass
    except Exception:
        pass
    NetForgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

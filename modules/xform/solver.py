"""
xform.solver
------------
Applies the transform to a stream of scalar symbols and checks each
resulting 32-byte state against the descriptor's target residual.
"""
import hashlib
import hmac
import os
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

try:
    from gpucore import DeviceContext, GPUError
except ModuleNotFoundError:
    from modules.gpucore import DeviceContext, GPUError
from .state import save_state, set_running


def _sha1(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()


def _hmac_sha1(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha1).digest()


def expand_scalar_cpu(scalar: bytes, basis: bytes, rounds: int = 4096) -> bytes:
    """Full 32-byte PBKDF2-HMAC-SHA1 (WPA2 PMK). Needs 2 blocks."""
    out = bytearray()
    for block_idx in (1, 2):
        msg = basis + block_idx.to_bytes(4, "big")
        U = _hmac_sha1(scalar, msg)
        acc = bytearray(U)
        for _ in range(rounds - 1):
            U = _hmac_sha1(scalar, U)
            for i in range(len(U)):
                acc[i] ^= U[i]
        out.extend(acc)
    return bytes(out[:32])


def _cpu_pmk_batch(args):
    scalars, basis, rounds = args
    return [expand_scalar_cpu(s, basis, rounds) for s in scalars]


_KERNEL_SRC_CACHE = None


def _load_kernel_source():
    global _KERNEL_SRC_CACHE
    if _KERNEL_SRC_CACHE is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "gpucore", "kernels", "expand_vector.cl")
        with open(path, "rb") as f:
            _KERNEL_SRC_CACHE = f.read().decode("utf-8")
    return _KERNEL_SRC_CACHE


class Solver:
    def __init__(self, descriptor, backend="auto", device_index=0,
                 batch_size=20000, log=None, stop_flag=None,
                 cpu_percent=30, notify_cb=None, save_every=50000):
        self.d = descriptor
        self.batch_size = batch_size
        self.log = log or (lambda *_: None)
        self._stop = stop_flag or (lambda: False)
        self.cpu_percent = max(5, min(100, int(cpu_percent)))
        self.notify_cb = notify_cb or (lambda msg: None)
        self.save_every = save_every

        self.backend = backend
        self.ctx = None
        self.kernel = None
        self.rounds = 4096

        if backend in ("gpu", "auto"):
            try:
                self.ctx = DeviceContext(device_index)
                src = _load_kernel_source()
                self.kernel = self.ctx.compile(src, "expand_vector")
                self.log(f"[*] GPU ready: {self.ctx.device_name}")
                self.backend = "gpu"
            except (GPUError, OSError) as e:
                if backend == "gpu":
                    raise
                self.log(f"[*] GPU unavailable ({e}); using CPU backend.")
                self.backend = "cpu"
        else:
            self.backend = "cpu"

    def _residual_matches(self, state32: bytes) -> bool:
        d = self.d
        min_mac = min(d["u_left"], d["u_right"])
        max_mac = max(d["u_left"], d["u_right"])
        min_n = min(d["n_left"], d["n_right"])
        max_n = max(d["n_left"], d["n_right"])
        data = min_mac + max_mac + min_n + max_n

        ptk = bytearray()
        for i in range(4):
            ptk += _hmac_sha1(state32,
                              b"Pairwise key expansion\x00" + data + bytes([i]))
        kck = bytes(ptk[:16])
        calc = _hmac_sha1(kck, d["msg"])[:16]
        return hmac.compare_digest(calc, d["target"])

    def _gpu_batch(self, scalars):
        ctx = self.ctx
        n = len(scalars)
        max_len = max((len(s) for s in scalars), default=1)

        flat = bytearray(n * max_len)
        lens = [0] * n
        for i, s in enumerate(scalars):
            s = s[:max_len]
            flat[i * max_len: i * max_len + len(s)] = s
            lens[i] = len(s)

        import ctypes
        pw_buf = ctx.make_buffer(bytes(flat))
        len_buf = ctx.make_buffer(b"".join(
            int(x).to_bytes(4, "little", signed=False) for x in lens
        ))
        salt = self.d["basis"]
        salt_buf = ctx.make_buffer(salt)
        out_buf = ctx.make_empty_buffer(n * 32)

        self.kernel.set_arg_buffer(0, pw_buf)
        self.kernel.set_arg_buffer(1, len_buf)
        self.kernel.set_arg_buffer(2, salt_buf)
        self.kernel.set_arg_scalar(3, len(salt), "i")
        self.kernel.set_arg_scalar(4, max_len, "i")
        self.kernel.set_arg_scalar(5, self.rounds, "i")
        self.kernel.set_arg_buffer(6, out_buf)

        self.kernel.dispatch(n)
        out = ctx.read_buffer(out_buf, n * 32)

        for b in (pw_buf, len_buf, salt_buf, out_buf):
            ctx.release_buffer(b)

        return [out[i * 32:(i + 1) * 32] for i in range(n)]

    def _throttle(self, batch_start_time):
        """Sleep so average CPU stays near the requested percent."""
        if self.cpu_percent >= 95:
            return
        elapsed = time.time() - batch_start_time
        target = elapsed * (100.0 / self.cpu_percent)
        sleep_t = target - elapsed
        if sleep_t > 0.01:
            time.sleep(min(sleep_t, 5.0))

    def solve_generator(self, gen, total_estimate=-1, resume_info=None,
                        on_progress=None, job_meta=None):
        set_running(True)
        tested = resume_info.get("tested", 0) if resume_info else 0
        found = None
        last_notify = time.time()
        last_save = tested
        job_meta = job_meta or {}
        last_sym = None
        speed_window_t0 = time.time()
        speed_window_n0 = tested
        current_speed = 0.0

        try:
            batch = []
            for symbol in gen:
                if self._stop():
                    self.log("[*] Stop requested by user.")
                    break

                batch.append(symbol)
                if len(batch) < self.batch_size:
                    continue

                t0 = time.time()
                if self.backend == "gpu":
                    try:
                        states = self._gpu_batch(
                            [s.encode("utf-8", "ignore") for s in batch])
                    except GPUError as e:
                        self.log(f"[!] GPU failed ({e}); falling back to CPU.")
                        self.backend = "cpu"
                        states = [expand_scalar_cpu(
                            s.encode("utf-8", "ignore"), self.d["basis"], self.rounds)
                            for s in batch]
                else:
                    workers = max(1, int(mp.cpu_count() * self.cpu_percent / 100))
                    chunk = max(64, self.batch_size // max(1, workers))
                    encoded = [s.encode("utf-8", "ignore") for s in batch]
                    with ProcessPoolExecutor(max_workers=workers) as pool:
                        states = list(pool.map(
                            _cpu_pmk_batch,
                            [(encoded[i:i + chunk], self.d["basis"], self.rounds)
                             for i in range(0, len(encoded), chunk)]
                        ))
                        states = [s for sub in states for s in sub]

                for sym, st in zip(batch, states):
                    if self._residual_matches(st):
                        found = sym
                        break
                tested += len(batch)
                last_sym = batch[-1]
                batch = []

                self._throttle(t0)

                # rolling speed (tries/s)
                now = time.time()
                dt = now - speed_window_t0
                if dt >= 2.0:
                    current_speed = (tested - speed_window_n0) / dt
                    speed_window_t0 = now
                    speed_window_n0 = tested

                if on_progress:
                    on_progress(tested, total_estimate, last_sym, current_speed)

                if tested - last_save >= self.save_every:
                    state = {
                        "tested": tested,
                        "last_symbol": last_sym,
                        "found": None,
                        "speed": round(current_speed, 1),
                        **job_meta,
                    }
                    save_state(state)
                    last_save = tested

                if time.time() - last_notify >= 1800:
                    msg = (f"Progress: {tested:,} candidates tested"
                           + (f" / ~{total_estimate:,}" if total_estimate > 0 else "")
                           + f"\nSpeed: {current_speed:,.0f} tries/s"
                           + f"\nLast: {last_sym}")
                    self.notify_cb(msg)
                    last_notify = time.time()

                if found:
                    break

            # flush remaining
            if batch and not found and not self._stop():
                if self.backend == "gpu":
                    try:
                        states = self._gpu_batch(
                            [s.encode("utf-8", "ignore") for s in batch])
                    except GPUError:
                        states = [expand_scalar_cpu(
                            s.encode("utf-8", "ignore"), self.d["basis"], self.rounds)
                            for s in batch]
                else:
                    states = [expand_scalar_cpu(
                        s.encode("utf-8", "ignore"), self.d["basis"], self.rounds)
                        for s in batch]
                for sym, st in zip(batch, states):
                    if self._residual_matches(st):
                        found = sym
                        break
                tested += len(batch)
                last_sym = batch[-1] if batch else last_sym

            state = {
                "tested": tested,
                "last_symbol": last_sym,
                "found": found,
                **job_meta,
            }
            save_state(state)

            if found:
                self.notify_cb(f"KEY FOUND → {found}")
            return found

        finally:
            set_running(False)

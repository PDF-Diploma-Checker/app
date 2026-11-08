"""Live load of the GPU and the CPU while an analysis runs.

The numbers come from the operating system, not from the settings:
    GPU load, video memory, temperature  <- `nvidia-smi --query-gpu=...` (the same tool you can run in a terminal:
                                            `nvidia-smi -l 1` or `watch -n1 nvidia-smi`)
    CPU load                             <- /proc/stat (Linux) or GetSystemTimes (Windows)

ResourceMonitor samples in a background thread, so the UI only reads `latest` (cheap) and never waits for nvidia-smi.
When it is stopped it writes a one-line summary (peak and average) to the log: proof where the work really ran.
"""

import logging
import sys
import threading
import time

from common import system_info

logger = logging.getLogger(__name__)

_SMOOTH_SAMPLES = 5            # readings averaged for the number shown in the UI
_GPU_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu"


def gpu_live_stats():
    """Current state of the biggest NVIDIA card: {'util': %, 'mem_used_mb', 'mem_total_mb', 'temp': C} or None."""
    out = system_info._run(["nvidia-smi", f"--query-gpu={_GPU_QUERY}", "--format=csv,noheader,nounits"])
    best = None
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            stats = {
                "util": float(parts[0]), "mem_used_mb": float(parts[1]), "mem_total_mb": float(parts[2]),
                "temp": float(parts[3]) if parts[3].replace(".", "", 1).isdigit() else None,
            }
        except ValueError:
            continue
        if best is None or stats["mem_total_mb"] > best["mem_total_mb"]:
            best = stats
    return best


class CpuSampler:
    """CPU load in percent since the previous call to sample() (None when the platform gives no numbers)."""

    def __init__(self):
        self._last = self._read()

    @staticmethod
    def _read():
        """(busy, total) counters of all CPUs, or None."""
        try:
            if sys.platform.startswith("linux"):
                with open("/proc/stat", encoding="utf-8") as f:
                    values = [int(v) for v in f.readline().split()[1:]]
                idle = values[3] + (values[4] if len(values) > 4 else 0)     # idle + iowait
                total = sum(values[:8])
                return total - idle, total
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
                if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                    return None

                def value(ft):
                    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

                total = value(kernel) + value(user)          # kernel time already includes idle time
                return total - value(idle), total
        except Exception:
            logger.debug("Cannot read CPU counters", exc_info=True)
        return None

    def sample(self):
        now = self._read()
        last, self._last = self._last, now
        if not now or not last or now[1] <= last[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (now[0] - last[0]) / (now[1] - last[1])))


class ResourceMonitor:
    """Samples GPU and CPU every `interval` seconds in a background thread; read `latest` from any thread."""

    def __init__(self, interval=1.5, watch_gpu=True):
        self.interval = interval
        self.watch_gpu = watch_gpu
        self.latest = {}
        self._gpu_samples = []
        self._cpu_samples = []
        self._stop = threading.Event()
        self._thread = None
        self._cpu = CpuSampler()

    def start(self):
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="resource-monitor", daemon=True)
            self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            sample = {"time": time.monotonic(), "cpu": self._cpu.sample()}
            if self.watch_gpu:
                raw = gpu_live_stats()
                if raw:
                    self._gpu_samples.append(raw)
                    # the card is often idle for a moment while the processor works on the layers that did not fit
                    # into the video memory, so one reading can be 0% although the model sits on the GPU: show the
                    # average of the last few readings instead (the log summary keeps the real peak and average)
                    recent = self._gpu_samples[-_SMOOTH_SAMPLES:]
                    sample["gpu"] = dict(raw, util=sum(r["util"] for r in recent) / len(recent), util_now=raw["util"])
                else:
                    sample["gpu"] = None
            if sample["cpu"] is not None:
                self._cpu_samples.append(sample["cpu"])
            self.latest = sample
            self._stop.wait(self.interval)

    def stop(self):
        """Stop sampling and log the summary."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)
        logger.info("Resource usage during the analysis: %s", self.summary())

    def summary(self):
        parts = []
        if self._gpu_samples:
            utils = [s["util"] for s in self._gpu_samples]
            vram = max(s["mem_used_mb"] for s in self._gpu_samples)
            parts.append(f"GPU load avg {sum(utils) / len(utils):.0f}% / peak {max(utils):.0f}%, "
                         f"peak VRAM {vram / 1024:.1f} GB of {self._gpu_samples[-1]['mem_total_mb'] / 1024:.1f} GB")
        elif self.watch_gpu:
            parts.append("GPU: no data (nvidia-smi not available)")
        if self._cpu_samples:
            parts.append(f"CPU load avg {sum(self._cpu_samples) / len(self._cpu_samples):.0f}% / "
                         f"peak {max(self._cpu_samples):.0f}%")
        return "; ".join(parts) or "no data"


def format_stats(sample, t):
    """One status line for the UI from a ResourceMonitor sample; `t` is the translation function."""
    if not sample:
        return ""
    cpu = sample.get("cpu")
    cpu_text = f"{cpu:.0f}" if cpu is not None else "?"
    gpu = sample.get("gpu")
    if gpu:
        temp = f"{gpu['temp']:.0f}" if gpu.get("temp") is not None else "?"
        return t("analysis.stats_gpu", util=f"{gpu['util']:.0f}", used=f"{gpu['mem_used_mb'] / 1024:.1f}",
                 total=f"{gpu['mem_total_mb'] / 1024:.1f}", temp=temp, cpu=cpu_text)
    return t("analysis.stats_cpu", cpu=cpu_text)

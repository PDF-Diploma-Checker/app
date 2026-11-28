"""Checks whether this computer (and this build of the app) can run the AI analysis, and on what.

collect_facts() asks the system (slow: starts nvidia-smi, loads llama.cpp), diagnose() turns the facts into a list
of checks with advice. The two are separate so that diagnose() is a plain function that is easy to test.

The texts live in ui/translations.py (section "hw"); a Check only carries an id, a level and parameters.
"""

import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from importlib import metadata, util

from common import system_info

logger = logging.getLogger(__name__)

MIN_DRIVER_CUDA = (12, 0)       # the GPU build is compiled with CUDA 12.x
MIN_RAM_FOR_CPU_GB = 12.0       # Gemma 3 12B (Q4) needs about 8 GB for the weights plus working memory
GOOD_VRAM_GB = 8.0                  # the largest model fits whole on the card from here on
AI_MODELS_SIZE_GB = 14.0        # Gemma 3 12B + Qwen2.5-VL + projector + embeddings
NEEDED_FREE_GB = 15.0           # what the models folder should have free before downloading
LIGHT_MODELS_SIZE_GB = 9.0      # Gemma 3 4B + Qwen2.5-VL + projector + embeddings
LIGHT_NEEDED_FREE_GB = 10.0
LIGHT_GOOD_VRAM_GB = 4.0        # the small model fits whole on the card from here on
LIGHT_MIN_RAM_FOR_CPU_GB = 6.0


def models_size_gb(profile="full"):
    return LIGHT_MODELS_SIZE_GB if profile == "light" else AI_MODELS_SIZE_GB


def needed_free_gb(profile="full"):
    return LIGHT_NEEDED_FREE_GB if profile == "light" else NEEDED_FREE_GB


@dataclass
class Check:
    id: str
    level: str                          # "ok" | "warn" | "fail" | "info"
    params: dict = field(default_factory=dict)


@dataclass
class HardwareReport:
    checks: list
    gpu_usable: bool
    recommended_device: str             # "cuda" | "cpu"
    recommended_layers: int
    gpu_name: str = ""
    vram_gb: float = 0.0
    facts: dict = field(default_factory=dict)
    recommended_profile: str = "full"   # "light" for a computer that cannot run the 12B model well

    def as_text(self):
        """Plain-text form for the log and for bug reports."""
        lines = []
        for check in self.checks:
            params = ", ".join(f"{k}={v}" for k, v in check.params.items() if k != "howto")  # instructions, not facts
            lines.append(f"[{check.level}] {check.id}" + (f" ({params})" if params else ""))
        lines.append(f"recommended: device={self.recommended_device}, n_gpu_layers={self.recommended_layers}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- facts

def _parse_cuda_version(text):
    """'12.8' -> (12, 8); anything unreadable -> None."""
    try:
        major, _, minor = str(text).strip().partition(".")
        return int(major), int(minor or 0)
    except ValueError:
        return None


def nvidia_gpus():
    """NVIDIA cards reported by nvidia-smi: [{'name', 'driver', 'vram_gb', 'used_mb'}], biggest first."""
    out = system_info._run([
        "nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpus.append({
                "name": parts[0], "driver": parts[1],
                "vram_gb": float(parts[2]) / 1024.0, "used_mb": float(parts[3]),
            })
        except ValueError:
            continue
    return sorted(gpus, key=lambda g: g["vram_gb"], reverse=True)


def gpu_memory_used_mb():
    """Memory in use on the biggest NVIDIA card in MB, or None when it cannot be read."""
    gpus = nvidia_gpus()
    return gpus[0]["used_mb"] if gpus else None


def driver_cuda_version():
    """The newest CUDA version the installed NVIDIA driver supports, e.g. '12.8' (from the nvidia-smi header)."""
    smi = system_info._run(["nvidia-smi"])
    if smi and "CUDA Version:" in smi:
        return smi.split("CUDA Version:", 1)[1].split()[0]
    return None


def llama_gpu_support():
    """True when the bundled llama.cpp was compiled with GPU (CUDA) support."""
    try:
        import llama_cpp
        return bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return False


def total_ram_gb():
    """Installed RAM in GB (0.0 when unknown); no psutil needed."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys / 1024 ** 3
        if sys.platform == "darwin":
            out = system_info._run(["sysctl", "-n", "hw.memsize"])
            return int(out) / 1024 ** 3 if out else 0.0
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return 0.0


def torch_flavour():
    """Which torch build is installed, without importing it: 'cuda', 'cpu', 'unknown' or None (not installed)."""
    if util.find_spec("torch") is None:
        return None
    try:
        version = metadata.version("torch")
    except metadata.PackageNotFoundError:
        return "unknown"
    if "+cu" in version:
        return "cuda"
    if "+cpu" in version:
        return "cpu"
    return "unknown"


def free_space_gb(path):
    """Free space on the disk that holds `path` (which need not exist yet)."""
    probe = os.path.abspath(str(path))
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe).free / 1024 ** 3
    except OSError:
        return 0.0


def collect_facts(model_dir=None):
    """Gather everything diagnose() needs. Slow (external commands, loads llama.cpp): run it off the UI thread."""
    from analysis.modules.llm import config

    gpus = nvidia_gpus()
    return {
        "os": system_info.get_os_name(),
        "cpu": system_info.get_cpu_name(),
        "threads": os.cpu_count() or 0,
        "ram_gb": total_ram_gb(),
        "ai_runtime": config.llm_runtime_available(),
        "gpu_build": config.llm_runtime_available() and llama_gpu_support(),
        "nvidia": gpus[0] if gpus else None,
        "other_gpus": [g for g in system_info.get_gpu_info() if "NVIDIA" not in g.upper()] if not gpus else [],
        "driver_cuda": driver_cuda_version() if gpus else None,
        "torch": torch_flavour(),
        "java": config.java_available(),
        "java_version": config.java_version(),
        "profile": config.MODEL_PROFILE,
        "models_ready": config.are_ai_models_downloaded(),
        "model_dir": str(model_dir or config.MODEL_DIR),
        "free_gb": free_space_gb(model_dir or config.MODEL_DIR),
        "machine": platform.machine(),
    }


# --------------------------------------------------------------------------- advice

def is_weak_gpu(vram_gb, profile="full"):
    """A card that was found, but cannot hold the whole model: part of the work stays on the processor."""
    return 0 < vram_gb < (LIGHT_GOOD_VRAM_GB if profile == "light" else GOOD_VRAM_GB)


# A "16 GB" card reports about 15.9 GB (16311 MiB on an RTX 5060 Ti), so the limit sits a little below 16.
FULL_OFFLOAD_VRAM_GB = 15.5


def recommend_gpu_layers(vram_gb, profile="full"):
    """How many of Gemma's 48 layers to put on a card with this much memory (the rest stays on the CPU).

    A rule of thumb: the layers, the context buffers and the vision model have to fit together. The small model
    (profile "light", 34 layers) fits whole on a card with 5 GB or more."""
    if profile == "light":
        if vram_gb >= 5:
            return -1
        if vram_gb >= 3.5:
            return 20
        if vram_gb >= 2.5:
            return 10
        return 0
    if vram_gb >= FULL_OFFLOAD_VRAM_GB:
        return -1           # everything
    if vram_gb >= 10:
        return 40
    if vram_gb >= 7.5:
        return 25
    if vram_gb >= 5.5:
        return 16
    if vram_gb >= 3.5:
        return 8
    return 0


def recommend_profile(facts, vram_gb=0.0):
    """"light" (Gemma 4B) when this computer cannot run the 12B model well: a card with less memory than the model
    needs, or no usable card and little RAM. Otherwise "full"."""
    if facts.get("nvidia"):
        return "light" if vram_gb < GOOD_VRAM_GB else "full"
    ram = float(facts.get("ram_gb") or 0.0)
    return "light" if 0 < ram < MIN_RAM_FOR_CPU_GB else "full"


def diagnose(facts):
    """Turn collect_facts() output into a HardwareReport."""
    profile = facts.get("profile", "full")
    min_ram = LIGHT_MIN_RAM_FOR_CPU_GB if profile == "light" else MIN_RAM_FOR_CPU_GB
    checks = [
        Check("os", "info", {"os": facts.get("os", "?"), "machine": facts.get("machine", "")}),
        Check("cpu", "info", {"cpu": facts.get("cpu", "?"), "threads": facts.get("threads", 0)}),
    ]

    ram = float(facts.get("ram_gb") or 0.0)
    if ram > 0:
        level = "ok" if ram >= min_ram else "warn"
        checks.append(Check("ram", level, {"ram": f"{ram:.0f}", "needed": f"{min_ram:.0f}"}))

    ai_runtime = bool(facts.get("ai_runtime"))
    checks.append(Check("ai_runtime", "ok" if ai_runtime else "fail"))

    nvidia = facts.get("nvidia")
    driver_ok = False
    vram = 0.0
    gpu_name = ""
    if nvidia:
        gpu_name = nvidia["name"]
        vram = float(nvidia["vram_gb"])
        free_vram = max(vram - float(nvidia.get("used_mb", 0.0)) / 1024.0, 0.0)
        checks.append(Check("gpu", "ok", {"name": gpu_name, "vram": f"{vram:.1f}", "free": f"{free_vram:.1f}"}))

        cuda_text = facts.get("driver_cuda")
        cuda = _parse_cuda_version(cuda_text) if cuda_text else None
        driver_ok = cuda is None or cuda >= MIN_DRIVER_CUDA
        checks.append(Check(
            "driver", "ok" if driver_ok else "warn",
            {"driver": nvidia["driver"], "cuda": cuda_text or "?", "needed": "%d.%d" % MIN_DRIVER_CUDA},
        ))
        vram = free_vram                    # what other programs have not taken is what the model can use
        if is_weak_gpu(vram, profile):
            checks.append(Check("vram", "warn", {"vram": f"{vram:.1f}", "layers": recommend_gpu_layers(vram, profile)}))
    elif facts.get("other_gpus"):
        checks.append(Check("gpu_other", "warn", {"name": "; ".join(facts["other_gpus"])}))
    else:
        checks.append(Check("gpu_none", "warn"))

    gpu_build = bool(facts.get("gpu_build"))
    if ai_runtime:
        checks.append(Check("gpu_build", "ok" if gpu_build else "warn"))

    torch = facts.get("torch")
    if torch:
        checks.append(Check("torch", "info", {"flavour": torch}))

    java_version = facts.get("java_version")
    if facts.get("java"):
        checks.append(Check("java", "ok"))
    else:
        from analysis.modules.llm.config import JAVA_MIN_VERSION, java_howto
        if java_version:
            # found, but LanguageTool refuses to start on it
            checks.append(Check("java_old", "fail", {"version": java_version, "min": JAVA_MIN_VERSION,
                                                     "howto": java_howto()}))
        else:
            checks.append(Check("java", "fail", {"howto": java_howto()}))

    if not facts.get("models_ready"):
        free = float(facts.get("free_gb") or 0.0)
        checks.append(Check(
            "disk", "ok" if free >= needed_free_gb(profile) else "warn",
            {"free": f"{free:.0f}", "needed": f"{models_size_gb(profile):.0f}", "dir": facts.get("model_dir", "")},
        ))

    recommended_profile = recommend_profile(facts, vram)
    gpu_usable = bool(ai_runtime and gpu_build and nvidia and driver_ok
                      and (recommend_gpu_layers(vram, profile) != 0 or recommend_gpu_layers(vram, recommended_profile) != 0))
    return HardwareReport(
        checks=checks,
        gpu_usable=gpu_usable,
        recommended_device="cuda" if gpu_usable else "cpu",
        recommended_layers=recommend_gpu_layers(vram, recommended_profile) if gpu_usable else 0,
        gpu_name=gpu_name,
        vram_gb=vram,
        facts=facts,
        recommended_profile=recommended_profile,
    )


def check_hardware(model_dir=None):
    """collect_facts() + diagnose(); the log gets the result."""
    report = diagnose(collect_facts(model_dir))
    logger.info("Hardware check:\n%s", report.as_text())
    return report
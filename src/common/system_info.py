"""Best-effort OS, GPU driver and CUDA details for bug reports; failures yield "none"."""

import logging
import platform
import shutil
import subprocess
import sys
from importlib import metadata

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_S = 10
NONE = "none"


def _run(cmd):
    """Return a command's stdout, or None if it's missing or fails. Hides the console on Windows."""

    if shutil.which(cmd[0]) is None:
        return None

    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S,
            encoding="utf-8", errors="replace", **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("System info probe failed: %s", cmd[0], exc_info=True)
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip() or None


def get_os_name():
    """Return the OS name and version, e.g. 'Ubuntu 26.04 LTS'."""

    if sys.platform.startswith("linux"):
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            return f"Linux (nieznana dystrybucja), kernel {platform.release()}"
        name = release.get("PRETTY_NAME") or f"{release.get('NAME', 'Linux')} {release.get('VERSION_ID', '')}"
        return f"{name.strip()}, kernel {platform.release()}"

    if sys.platform == "win32":
        return _get_windows_name()

    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"

    return platform.platform()


def _get_windows_name():
    """Return e.g. 'Windows 11 Pro 24H2 (build 26100)'; Windows 11 is detected by build number."""
    version, build, *_ = platform.win32_ver()
    edition = platform.win32_edition() or ""

    try:
        build_number = int(build.split(".")[-1])
    except ValueError:
        build_number = 0
    major = "11" if build_number >= 22000 else platform.release()

    display_version = None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        ) as key:
            display_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
    except OSError:
        pass

    parts = [f"Windows {major}", edition, display_version, f"(build {build})"]
    return " ".join(p for p in parts if p)


def get_cpu_name():
    """Return the CPU model; read from /proc/cpuinfo on Linux."""

    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass

    return platform.processor() or NONE


def get_gpu_info():
    """Return 'GPU - driver' lines from nvidia-smi, PowerShell or lspci."""

    gpus = []

    nvidia = _run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    if nvidia:
        for line in nvidia.splitlines():
            name, _, driver = line.partition(",")
            gpus.append(f"{name.strip()} - sterownik NVIDIA {driver.strip()}")
        return gpus

    if sys.platform == "win32":
        out = _run([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { $_.Name + '|' + $_.DriverVersion }",
        ])
        for line in (out or "").splitlines():
            name, _, driver = line.partition("|")
            gpus.append(f"{name.strip()} - sterownik {driver.strip() or NONE}")

    elif sys.platform.startswith("linux"):
        gpus.extend(_get_linux_gpus())

    return gpus


def _get_linux_gpus():
    """Return display controllers and their kernel drivers from `lspci -k`."""

    out = _run(["lspci", "-k"])
    if not out:
        return []

    gpus = []
    current = None
    for line in out.splitlines():
        if not line.startswith(("\t", " ")):
            current = None
            if any(t in line for t in ("VGA compatible controller", "3D controller", "Display controller")):
                current = line.split(": ", 1)[-1].strip()
                gpus.append(current)
        elif current and "Kernel driver in use:" in line:
            driver = line.split(":", 1)[1].strip()
            gpus[-1] = f"{current} - sterownik {driver} {_linux_driver_version(driver)}".rstrip()

    return gpus


def _linux_driver_version(driver):
    """Return the kernel module version, or the kernel version for in-tree drivers."""

    try:
        with open(f"/sys/module/{driver}/version", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return f"(kernel {platform.release()})"


def get_cuda_info():
    """Return CUDA versions of the driver, nvcc toolkit and torch."""

    driver_cuda = NONE
    smi = _run(["nvidia-smi"])
    if smi and "CUDA Version:" in smi:
        driver_cuda = smi.split("CUDA Version:", 1)[1].split()[0]

    toolkit = NONE
    nvcc = _run(["nvcc", "--version"])
    if nvcc and "release" in nvcc:
        toolkit = nvcc.split("release", 1)[1].split(",")[0].strip()

    return {
        "CUDA (sterownik)": driver_cuda,
        "CUDA (toolkit nvcc)": toolkit,
        "torch": _get_torch_info(),
    }


def _get_torch_info():
    """Query torch only if already imported; otherwise read its version, e.g. 2.9.0+cu128."""
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            available = torch.cuda.is_available()
            device = torch.cuda.get_device_name(0) if available else NONE
            return f"{torch.__version__}, CUDA build {torch.version.cuda or NONE}, dostepna: {available}, GPU: {device}"
        except Exception:
            logger.warning("Failed to query torch CUDA status", exc_info=True)

    try:
        return f"{metadata.version('torch')} (nie zaladowany)"
    except metadata.PackageNotFoundError:
        return NONE


def _package_version(name):
    """Return an installed package's version or 'none'."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return NONE


def build_system_report():
    """Return a multi-line machine summary."""

    lines = [
        f"System: {get_os_name()}",
        f"Architektura: {platform.machine()}",
        f"Procesor: {get_cpu_name()}",
        f"Python: {platform.python_version()}",
    ]

    gpus = get_gpu_info()
    lines.append("GPU:" if gpus else f"GPU: {NONE}")
    lines.extend(f"  - {gpu}" for gpu in gpus)

    for label, value in get_cuda_info().items():
        lines.append(f"{label}: {value}")

    lines.append(f"llama-cpp-python: {_package_version('llama-cpp-python')}")

    return "\n".join(lines) + "\n"

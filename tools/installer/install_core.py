"""What the installer does, without its window, so that it can be tested on its own.

The files come from the same manifest and pack parts as a differential update, so there are no archives to join. They
are put together in a folder next to the target and moved in at the end. Only the entries of the app are replaced:
models, logs and anything else in the folder stay.
"""

import locale
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import delta, gpu_check, update_check, updater
from common.update_errors import UpdateCancelled, UpdateError

logger = logging.getLogger(__name__)

APP_DIR_NAME = delta.APP_DIR_NAME
VARIANTS = ("gpu", "cpu", "base")
_ANY_VERSION = "0"
ATTEMPTS = 5
RETRY_WAIT_S = 15
RETRIED_ERRORS = ("http", "range", "no_manifest")    # GitHub answers 504 for a while, the files themselves are fine
_CREATE_NO_WINDOW = 0x08000000
_SHORTCUT_SCRIPT = (
    "$folder=[Environment]::GetFolderPath($env:DC_FOLDER);"
    "$link=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'DiplomaChecker.lnk'));"
    "$link.TargetPath=$env:DC_TARGET;$link.WorkingDirectory=$env:DC_DIR;$link.Save()"
)


def language():
    """Polish on a Polish system: "pl_PL" on Linux, "Polish_Poland" on Windows."""
    return "pl" if (locale.getlocale()[0] or "").lower().startswith(("pl", "polish")) else "en"


def latest_release():
    """{"version", "tag", "assets"} of the newest release."""
    info = update_check.check_for_update(current=_ANY_VERSION)
    if not info:
        raise UpdateError("no_release")
    return info


def recommended_variant(gpus):
    """GPU with an NVIDIA card. A small card too: the part of the model that does not fit stays on the processor."""
    return "gpu" if any(gpu["vram_gb"] > 0 for gpu in gpus) else "cpu"


def detect_gpus():
    return gpu_check.nvidia_gpus()


def variant_sizes(info, platform):
    """{variant: bytes of its download}; a variant that this release does not offer is left out."""
    sizes = {}
    names = {a["name"]: int(a.get("size") or 0) for a in info["assets"]}
    for variant in VARIANTS:
        if delta.manifest_name(platform, variant) not in names:
            continue
        archive = updater.archive_name(platform, variant)
        sizes[variant] = sum(size for name, size in names.items()
                             if name == archive or (name.startswith(archive + ".") and not name.endswith(".sha256")))
    return sizes


def default_target():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def _is_app(folder):
    return (folder / "_internal").is_dir()


def resolve_target(chosen):
    """The folder to install into: an app's own or an empty one, else a new subfolder, so nothing is mixed with it."""
    chosen = Path(chosen).expanduser().resolve()
    if not chosen.exists() or _is_app(chosen) or not any(chosen.iterdir()):
        return chosen
    return chosen / APP_DIR_NAME


def _exists(path):
    return path.exists() or path.is_symlink()


def _swap(staging, target):
    """Move the new entries into `target`. The old ones are renamed first: on Windows a running app makes that fail
    before anything has changed."""
    target.mkdir(parents=True, exist_ok=True)
    old = target.with_name(target.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir()
    replaced = []
    try:
        for entry in list(staging.iterdir()):
            current = target / entry.name
            if _exists(current):
                os.replace(current, old / entry.name)
                replaced.append(entry.name)
            os.replace(entry, current)
    except OSError as e:
        for name in replaced:
            if _exists(target / name):
                os.replace(target / name, staging / name)
            os.replace(old / name, target / name)
        shutil.rmtree(old, ignore_errors=True)
        raise UpdateError("locked") from e
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)


def _wait(seconds, cancelled):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancelled():
            raise UpdateCancelled()
        time.sleep(0.2)


def _fetch(info, variant, platform, target, staging, progress, cancelled):
    plan = updater.plan_update(info, variant=variant, platform=platform)
    if not plan.manifest:
        raise UpdateError("no_manifest")
    work = delta.compute_delta(plan.manifest, target, staging, lambda d, t: progress("compare", d, t), cancelled)
    delta.stage_delta(plan.manifest, work, plan.pack_parts, staging, lambda d, t: progress("download", d, t), cancelled,
                      user_agent="DiplomaChecker-installer")


def install(info, variant, platform, target, progress, cancelled):
    """Install `variant` of release `info` into `target`. What was already fetched is not fetched again.
    progress(stage, done, total), stage: "compare", "download" or "retry"."""
    target = Path(target)
    staging = target.with_name(target.name + ".installing")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            _fetch(info, variant, platform, target, staging, progress, cancelled)
            break
        except UpdateError as e:
            if e.code not in RETRIED_ERRORS or attempt == ATTEMPTS:
                raise
            logger.warning("Download failed (%r), trying again", e)
            progress("retry", attempt, ATTEMPTS)
            _wait(RETRY_WAIT_S, cancelled)
    _swap(staging, target)
    return target


def executable(target):
    return Path(target) / (f"{APP_DIR_NAME}.exe" if sys.platform == "win32" else APP_DIR_NAME)


def _desktop_entry(target):
    target_path = Path(target)
    exec_path = executable(target_path).as_posix().replace('"', '\\"')
    icon_path = (target_path / "_internal" / "ui" / "assets" / "logo.png").as_posix()

    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=DiplomaChecker\n"
        "Comment=PDF thesis checker\n"
        f'Exec="{exec_path}"\n'
        f"Icon={icon_path}\n"
        "Terminal=false\n"
        "Categories=Office;Education;\n"
    )


def _windows_shortcut(target, folder):
    env = {**os.environ, "DC_FOLDER": folder, "DC_TARGET": str(executable(target)), "DC_DIR": str(target)}
    subprocess.run(["powershell", "-NoProfile", "-Command", _SHORTCUT_SCRIPT], env=env, check=True, timeout=30,
                   creationflags=_CREATE_NO_WINDOW, capture_output=True)


def create_shortcuts(target, desktop=False):
    """The menu entry, and on Windows the desktop icon when asked for. False when it failed: the app itself is fine."""
    try:
        if sys.platform == "win32":
            _windows_shortcut(target, "Programs")
            if desktop:
                _windows_shortcut(target, "DesktopDirectory")
        else:
            entry = Path.home() / ".local" / "share" / "applications" / "diplomachecker.desktop"
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(_desktop_entry(target), encoding="utf-8")
        return True
    except (OSError, subprocess.SubprocessError):
        logger.exception("Could not create the shortcuts")
        return False


def clean_environment():
    """The environment for the installed app, without what this one-file build set for itself."""
    env = dict(os.environ)
    for name in ("TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(name, None)
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def launch(target):
    subprocess.Popen([str(executable(target))], cwd=str(target), env=clean_environment(), start_new_session=True)

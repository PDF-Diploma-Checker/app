"""Updating the app in place: download the new version, swap the program files, keep the user's data.

Why this is cheap for the user
    The program is a folder (PyInstaller "onedir"):  DiplomaChecker(.exe)  +  _internal/
    Everything the user owns lives next to it and is never touched by an update:
        models/   (13 GB of AI models)      logs/      data/  (settings, history, LanguageTool)
    An update only replaces the executable and `_internal/`; nothing has to be installed again and the models are not
    downloaded again.

How an update runs
    1. update_check.check_for_update() finds a newer release and the list of its files (assets).
    2. plan_update()   picks the archive for this operating system and variant (base / cpu / gpu), see archive_name().
    3. stage_update()  downloads it (resumable), checks the checksum, unpacks it into  <install>/.update/new/
                       and validates it. Nothing of the running program is changed yet.
    4. apply_update_and_restart()  starts a small helper script and the app quits. The script waits until the app has
                       ended, swaps the entries of the new package in by renaming (same disk: instant), and starts the
                       new version. When anything fails, the old files are renamed back and the old version starts.
    5. finish_pending_update() at the next start reads the result of the helper and removes the leftovers.

Release files (see tools/prepare_release_assets.py)
    DiplomaChecker-windows-<variant>.zip      DiplomaChecker-linux-<variant>.tar.gz
    A GitHub release file may be at most 2 GiB. A bigger archive is published in parts  <archive>.001, .002, ...
    (they are joined again here) and may come with  <archive>.sha256  holding the SHA-256 of the whole archive.
    Differential update (common/delta.py): DiplomaChecker-<platform>-<variant>.manifest.json + .pack.001, .002, ...
    With them only the files that changed are downloaded (a few MB instead of GB); the full archive stays as the
    fallback and for first installs.

No Qt in this module, so it can be tested on its own.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from common import delta
from common.update_errors import UpdateCancelled, UpdateError
from common.version import APP_VERSION

logger = logging.getLogger(__name__)

APP_DIR_NAME = "DiplomaChecker"
PRESERVE = delta.PRESERVE                               # top-level entries an update never touches
CHUNK = 1024 * 1024
REQUEST_TIMEOUT_S = (10, 30)
SPACE_FACTOR = 2.5                                      # archive + unpacked files + a margin


@dataclass
class UpdatePlan:
    version: str
    archive: str                    # file name, e.g. DiplomaChecker-linux-gpu.tar.gz
    parts: list                     # [{"name", "size", "url"}] in order (one item unless the archive is split)
    total_size: int                 # bytes to download: the changed files when `delta` is set, else the whole archive
    sha256: str = ""                # of the whole archive, "" when unknown
    full_size: int = 0              # size of the whole package
    manifest: dict = None           # differential update: manifest of the release, None = full archive only
    pack_parts: list = field(default_factory=list)      # [{"name", "size", "url"}] of the pack
    delta: object = None            # delta.DeltaPlan once prepare_delta() has compared the files


@dataclass
class StagedUpdate:
    version: str
    new_dir: str                    # .update/new/DiplomaChecker


# --------------------------------------------------------------------------- where and what
def install_dir():
    """Folder that holds the executable (the app's own folder)."""
    return Path(sys.executable).resolve().parent


def update_dir():
    return install_dir() / ".update"


def platform_name():
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def exe_name():
    return f"{APP_DIR_NAME}.exe" if sys.platform == "win32" else APP_DIR_NAME


def current_variant():
    """'base' (no AI libraries), 'cpu' or 'gpu' (llama.cpp built with CUDA). Loads llama.cpp: not for the UI thread."""
    import importlib.util
    if importlib.util.find_spec("llama_cpp") is None:
        return "base"
    try:
        import llama_cpp
        return "gpu" if llama_cpp.llama_supports_gpu_offload() else "cpu"
    except Exception:
        return "cpu"


def archive_name(platform, variant):
    extension = "zip" if platform == "windows" else "tar.gz"
    return f"{APP_DIR_NAME}-{platform}-{variant}.{extension}"


def _writable(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def can_self_update():
    """(True, "") or (False, reason code) for this copy of the app."""
    if not getattr(sys, "frozen", False):
        return False, "source"                  # running from the source tree: update with git
    if platform_name() is None:
        return False, "platform"
    if not _writable(install_dir()):
        return False, "readonly"
    if platform_name() == "windows" and not shutil.which("powershell"):
        return False, "no_shell"
    if platform_name() == "linux" and not shutil.which("bash"):
        return False, "no_shell"
    return True, ""


# --------------------------------------------------------------------------- planning
def _digest(asset):
    value = str((asset or {}).get("digest") or "")
    return value.split(":", 1)[1].lower() if value.startswith("sha256:") else ""


def _find_parts(assets, name):
    """The release files of one archive (a single file or  name.001, name.002, ...), or None."""
    if name in assets:
        return [assets[name]]
    pattern = re.compile(rf"^{re.escape(name)}\.(\d{{3}})$")
    numbered = sorted((int(m.group(1)), a) for n, a in assets.items() if (m := pattern.match(n)))
    if not numbered or [n for n, _ in numbered] != list(range(1, len(numbered) + 1)):
        return None
    return [a for _, a in numbered]


def _find_manifest(info, assets, platform, variant):
    """(manifest, pack parts) of the differential update, or (None, []) when the release has none or it is unusable."""
    asset = assets.get(delta.manifest_name(platform, variant))
    if not asset or not asset.get("url"):
        return None, []
    try:
        response = requests.get(asset["url"], timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        manifest = delta.validate_manifest(response.json())
        if str(manifest.get("version", "")).lstrip("vV") != str(info["version"]).lstrip("vV"):
            raise UpdateError("invalid")
        pack = []
        for part in manifest["parts"]:
            found = assets.get(part["name"])
            if not found or not found.get("url") or int(found.get("size", part["size"])) != int(part["size"]):
                raise UpdateError("no_asset", name=part["name"])
            pack.append({"name": part["name"], "size": int(part["size"]), "url": found["url"]})
        return manifest, pack
    except (requests.RequestException, ValueError, UpdateError) as e:
        logger.warning("Differential update not available (%r), the full archive is used", e)
        return None, []


def plan_update(info, variant=None, platform=None):
    """UpdatePlan for the files of release `info` (from update_check.check_for_update), or UpdateError('no_asset')."""
    platform = platform or platform_name()
    variant = variant or current_variant()
    name = archive_name(platform, variant)
    assets = {a.get("name"): a for a in info.get("assets", []) if a.get("name")}

    parts = _find_parts(assets, name)
    manifest, pack = _find_manifest(info, assets, platform, variant)
    if parts is None and manifest is None:
        raise UpdateError("no_asset", name=name)

    sha = ""
    if parts:
        sha = _digest(parts[0]) if len(parts) == 1 else ""
        sidecar = assets.get(name + ".sha256")
        if sidecar and sidecar.get("url"):
            try:
                text = requests.get(sidecar["url"], timeout=REQUEST_TIMEOUT_S).text
                found = re.search(r"\b([0-9a-fA-F]{64})\b", text)
                if found:
                    sha = found.group(1).lower()
            except requests.RequestException:
                logger.warning("Could not read %s", name + ".sha256")
        if not sha:
            logger.warning("No checksum published for %s: only the size is checked", name)

    full = sum(int(p.get("size", 0)) for p in parts) if parts else sum(p["size"] for p in pack)
    return UpdatePlan(
        version=info["version"], archive=name if parts else "",
        parts=[{"name": p["name"], "size": int(p.get("size", 0)), "url": p["url"]} for p in parts or []],
        total_size=full, sha256=sha, full_size=full, manifest=manifest, pack_parts=pack,
    )


def prepare_delta(plan, progress=lambda d, t: None, cancelled=lambda: False):
    """Compare the installed files with the manifest (reads every installed file once: not for the UI thread).
    Afterwards plan.total_size is the size of the download. Without a manifest nothing happens. When the comparison
    fails the plan falls back to the full archive (or raises when there is none)."""
    if not plan.manifest or plan.delta is not None:
        return
    try:
        plan.delta = delta.compute_delta(plan.manifest, install_dir(), update_dir() / "new" / APP_DIR_NAME,
                                         progress, cancelled)
        plan.total_size = plan.delta.transfer
    except UpdateCancelled:
        raise
    except Exception as e:
        logger.exception("Comparing the installed files failed")
        if not plan.parts:
            raise UpdateError("generic", error=str(e)) from e
        plan.manifest, plan.delta, plan.total_size = None, None, plan.full_size


def free_bytes(path):
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


# --------------------------------------------------------------------------- download
def _download_part(part, dest, progress, cancelled, base_done, total):
    """Download one file with resume. progress(done_bytes, total_bytes)."""
    size = part["size"]
    have = dest.stat().st_size if dest.exists() else 0
    if size and have > size:
        dest.unlink()
        have = 0
    if size and have == size:
        progress(base_done + size, total)
        return

    headers = {"User-Agent": f"DiplomaChecker/{APP_VERSION}"}
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        with requests.get(part["url"], headers=headers, stream=True, timeout=REQUEST_TIMEOUT_S) as response:
            if response.status_code == 200 and have:
                have = 0                            # the server ignored the range: start over
            elif response.status_code not in (200, 206):
                raise UpdateError("http", status=response.status_code)
            mode = "ab" if have else "wb"
            done = have
            with open(dest, mode) as out:
                for chunk in response.iter_content(CHUNK):
                    if cancelled():
                        raise UpdateCancelled()
                    out.write(chunk)
                    done += len(chunk)
                    progress(base_done + done, total)
    except requests.RequestException as e:
        raise UpdateError("network", error=str(e)) from e

    if size and dest.stat().st_size != size:
        raise UpdateError("size", name=part["name"])


def download(plan, directory, progress, cancelled):
    """Download all parts into `directory`; returns their paths in order."""
    directory.mkdir(parents=True, exist_ok=True)
    paths, done = [], 0
    for part in plan.parts:
        path = directory / part["name"]
        _download_part(part, path, progress, cancelled, done, plan.total_size)
        done += part["size"]
        paths.append(path)
    return paths


def sha256_of(paths, cancelled=lambda: False):
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK):
                if cancelled():
                    raise UpdateCancelled()
                digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- unpack
class _ConcatReader:
    """Reads several files one after the other as one stream (for a split .tar.gz; no extra disk space)."""

    def __init__(self, paths):
        self._paths = list(paths)
        self._index = 0
        self._file = open(self._paths[0], "rb")
        self.position = 0

    def read(self, size=-1):
        out = b""
        while size < 0 or len(out) < size:
            chunk = self._file.read(-1 if size < 0 else size - len(out))
            if not chunk:
                self._file.close()
                self._index += 1
                if self._index >= len(self._paths):
                    break
                self._file = open(self._paths[self._index], "rb")
                continue
            out += chunk
        self.position += len(out)
        return out

    def close(self):
        if not self._file.closed:
            self._file.close()


def _inside(base, target):
    base, target = Path(os.path.abspath(base)), Path(os.path.abspath(target))
    return target == base or base in target.parents


def _extract_zip(paths, dest, progress, cancelled):
    archive = paths[0]
    if len(paths) > 1:                                      # a zip needs random access: join the parts, freeing each
        joined = paths[0].with_name("joined.zip")
        with open(joined, "wb") as out:
            for path in paths:
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, out, CHUNK)
                path.unlink()
        archive = joined
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        total = sum(m.file_size for m in members) or 1
        done = 0
        for member in members:
            if cancelled():
                raise UpdateCancelled()
            if not _inside(dest, dest / member.filename):
                raise UpdateError("unsafe", name=member.filename)
            zf.extract(member, dest)
            done += member.file_size
            progress(done, total)


def _extract_tar(paths, dest, progress, cancelled):
    total = sum(p.stat().st_size for p in paths) or 1
    reader = _ConcatReader(paths)
    try:
        with tarfile.open(fileobj=reader, mode="r|gz") as tar:
            for member in tar:
                if cancelled():
                    raise UpdateCancelled()
                if not _inside(dest, dest / member.name):
                    raise UpdateError("unsafe", name=member.name)
                if member.issym() or member.islnk():
                    link = Path(member.linkname)
                    target = link if link.is_absolute() else Path(member.name).parent / link
                    if link.is_absolute() or not _inside(dest, dest / target):
                        raise UpdateError("unsafe", name=member.name)
                try:
                    tar.extract(member, dest, filter="data")
                except TypeError:                           # Python without extraction filters: checked above
                    tar.extract(member, dest)
                progress(reader.position, total)
    finally:
        reader.close()


def unpack(paths, dest, progress, cancelled):
    """Unpack the archive (a zip or a tar.gz, possibly split in parts) into `dest`. progress(done, total)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if str(paths[0].name).endswith(".zip") or ".zip." in paths[0].name:
        _extract_zip(paths, dest, progress, cancelled)
    else:
        _extract_tar(paths, dest, progress, cancelled)


def validate_package(new_dir):
    """The unpacked folder must look like this app. Returns its path or raises UpdateError('invalid')."""
    package = Path(new_dir) / APP_DIR_NAME
    if not (package / exe_name()).is_file() or not (package / "_internal").is_dir():
        raise UpdateError("invalid")
    return package


# --------------------------------------------------------------------------- stage
FALLBACK_CODES = ("range", "http", "checksum", "invalid", "size")      # a differential update that may be retried in full


def _finish_stage(plan, root):
    package = validate_package(root / "new")
    staged = StagedUpdate(version=plan.version, new_dir=str(package))
    (root / "ready.json").write_text(json.dumps({"version": staged.version, "new_dir": staged.new_dir}),
                                     encoding="utf-8")
    return staged


def _stage_delta(plan, root, progress, cancelled):
    prepare_delta(plan, lambda d, t: progress("compare", d, t), cancelled)
    if not plan.manifest:
        return None                                 # the comparison failed: the caller downloads the full archive
    delta.stage_delta(
        plan.manifest, plan.delta, plan.pack_parts, root / "new" / APP_DIR_NAME,
        lambda d, t: progress("download", d, t), cancelled, user_agent=f"DiplomaChecker/{APP_VERSION}",
        progress_link=lambda d, t: progress("link", d, t),
    )
    return _finish_stage(plan, root)


def stage_update(plan, progress, cancelled):
    """Download (only the changed files when the release has a manifest), verify, unpack and validate.
    `progress(stage, done, total)`; stage is 'compare', 'link', 'download', 'verify' or 'unpack'.
    Raises UpdateError / UpdateCancelled. Nothing of the running app changes."""
    root = update_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "ready.json").unlink(missing_ok=True)

    if plan.manifest:
        try:
            staged = _stage_delta(plan, root, progress, cancelled)
            if staged is not None:
                return staged
        except UpdateError as e:
            if not plan.parts or e.code not in FALLBACK_CODES:
                raise
            logger.warning("Differential update failed (%s): downloading the full archive", e.code)
        shutil.rmtree(root / "new", ignore_errors=True)
        plan.manifest, plan.delta, plan.total_size = None, None, plan.full_size

    need = int(plan.total_size * SPACE_FACTOR)
    parent = install_dir()
    existing = sum(f.stat().st_size for f in (root / "download").glob("*") if f.is_file()) if root.exists() else 0
    if free_bytes(parent) + existing < need:
        raise UpdateError("space", free=free_bytes(parent), needed=need)

    paths = download(plan, root / "download", lambda d, t: progress("download", d, t), cancelled)

    if plan.sha256:
        progress("verify", 0, 1)
        if sha256_of(paths, cancelled) != plan.sha256:
            for path in paths:
                path.unlink(missing_ok=True)            # a corrupt download must not be resumed
            raise UpdateError("checksum")

    unpack(paths, root / "new", lambda d, t: progress("unpack", d, t), cancelled)
    shutil.rmtree(root / "download", ignore_errors=True)
    return _finish_stage(plan, root)


def staged_update():
    """An update downloaded earlier and not installed yet (the user chose "Later"), or None."""
    try:
        data = json.loads((update_dir() / "ready.json").read_text(encoding="utf-8"))
        from common.update_check import is_newer
        if is_newer(data["version"], APP_VERSION):
            validate_package(Path(data["new_dir"]).parent)
            return StagedUpdate(version=data["version"], new_dir=data["new_dir"])
    except (OSError, ValueError, KeyError, UpdateError):
        pass
    return None


# --------------------------------------------------------------------------- apply
_WINDOWS_SCRIPT = r'''param([int]$ProcId, [string]$Install, [string]$New, [string]$Exe, [string]$Preserve)
$ErrorActionPreference = "Stop"
$updateDir = Join-Path $Install ".update"
$result = Join-Path $updateDir "result.txt"
function Log($m) { Add-Content -LiteralPath (Join-Path $updateDir "update.log") -Value ("{0} {1}" -f (Get-Date -Format s), $m) }
function Retry($action) {
    for ($i = 0; $i -lt 40; $i++) {
        try { & $action; return } catch { Start-Sleep -Milliseconds 750; $last = $_ }
    }
    throw $last
}
$keep = $Preserve -split ","
$done = @()
try {
    try { Wait-Process -Id $ProcId -Timeout 120 -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 1
    Log "swap start"
    foreach ($item in Get-ChildItem -LiteralPath $New -Force) {
        $name = $item.Name
        if ($keep -contains $name) { continue }
        $dst = Join-Path $Install $name
        $old = "$dst.old"
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
        $had = Test-Path -LiteralPath $dst
        if ($had) { Retry { Move-Item -LiteralPath $dst -Destination $old } }
        $done += ,@($name, $had)
        Retry { Move-Item -LiteralPath $item.FullName -Destination $dst }
    }
    Set-Content -LiteralPath $result -Value "ok"
    Log "swap done"
} catch {
    Log ("swap failed: " + $_)
    [array]::Reverse($done)
    foreach ($entry in $done) {
        $dst = Join-Path $Install $entry[0]
        try {
            if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
            if ($entry[1]) { Move-Item -LiteralPath "$dst.old" -Destination $dst }
        } catch { Log ("rollback problem: " + $_) }
    }
    Set-Content -LiteralPath $result -Value ("failed: " + $_)
}
Start-Process -FilePath (Join-Path $Install $Exe) -WorkingDirectory $Install
'''

_LINUX_SCRIPT = r'''#!/usr/bin/env bash
# args: PID INSTALL NEW EXE PRESERVE(comma separated)
PID="$1"; INSTALL="$2"; NEW="$3"; EXE="$4"; PRESERVE="$5"
UPDATE="$INSTALL/.update"
RESULT="$UPDATE/result.txt"
log() { echo "$(date +%FT%T) $*" >> "$UPDATE/update.log"; }
keep() { case ",$PRESERVE," in *",$1,"*) return 0;; esac; return 1; }

for _ in $(seq 1 240); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
sleep 1
log "swap start"
done_list=()
fail=""
shopt -s dotglob nullglob
for item in "$NEW"/*; do
    name="$(basename "$item")"
    keep "$name" && continue
    dst="$INSTALL/$name"
    rm -rf "$dst.old"
    had=0
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        had=1
        mv "$dst" "$dst.old" || { fail="cannot move $name away"; break; }
    fi
    done_list+=("$name:$had")
    mv "$item" "$dst" || { fail="cannot move $name in"; break; }
done
if [ -n "$fail" ]; then
    log "swap failed: $fail"
    for ((i=${#done_list[@]}-1; i>=0; i--)); do
        entry="${done_list[$i]}"; name="${entry%%:*}"; had="${entry##*:}"
        rm -rf "$INSTALL/$name"
        if [ "$had" = "1" ]; then mv "$INSTALL/$name.old" "$INSTALL/$name"; fi
    done
    echo "failed: $fail" > "$RESULT"
else
    echo "ok" > "$RESULT"
    log "swap done"
fi
cd "$INSTALL" && nohup "$INSTALL/$EXE" >/dev/null 2>&1 &
'''


def _write_script(staged):
    root = update_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.txt").unlink(missing_ok=True)
    if platform_name() == "windows":
        script = root / "apply_update.ps1"
        script.write_text(_WINDOWS_SCRIPT, encoding="utf-8-sig")        # BOM: PowerShell 5 reads it as UTF-8
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                   "-File", str(script), "-ProcId", str(os.getpid()), "-Install", str(install_dir()),
                   "-New", staged.new_dir, "-Exe", exe_name(), "-Preserve", ",".join(PRESERVE)]
    else:
        script = root / "apply_update.sh"
        script.write_text(_LINUX_SCRIPT, encoding="utf-8")
        script.chmod(0o755)
        command = ["bash", str(script), str(os.getpid()), str(install_dir()), staged.new_dir, exe_name(),
                   ",".join(PRESERVE)]
    return command


def apply_update_and_restart(staged):
    """Start the helper that swaps the files after this process has ended. The caller must quit the app right after."""
    ok, reason = can_self_update()
    if not ok:
        raise UpdateError("cannot", reason=reason)
    validate_package(Path(staged.new_dir).parent)
    command = _write_script(staged)
    logger.info("Starting the update helper for version %s", staged.version)
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, **kwargs)


# --------------------------------------------------------------------------- after the swap
def finish_pending_update():
    """Call once at start-up. Returns {"status": "ok"|"failed", "message": str, "log": str} when an update was just
    installed (or failed), else None. Leftovers (the old version, unpacked files) are removed in the background."""
    root = update_dir()
    result_file = root / "result.txt"
    outcome = None
    try:
        if result_file.is_file():
            text = result_file.read_text(encoding="utf-8", errors="replace").strip()
            outcome = {"status": "ok" if text == "ok" else "failed", "message": text, "log": str(root / "update.log")}
            result_file.unlink()
            logger.info("Update result: %s", text)
    except OSError:
        logger.exception("Cannot read the update result")
    if root.exists() or any(install_dir().glob("*.old")):
        threading.Thread(target=_cleanup, args=(outcome is not None,), daemon=True, name="update-cleanup").start()
    return outcome


def _cleanup(after_swap):
    """Remove `*.old` and the unpacked update. A staged update that was not installed yet is kept."""
    base = install_dir()
    try:
        for old in base.glob("*.old"):
            shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
        root = update_dir()
        if after_swap or not (root / "ready.json").is_file():
            for name in ("new", "download", "ready.json", "apply_update.ps1", "apply_update.sh"):
                target = root / name
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
    except Exception:
        logger.exception("Update cleanup failed")
"""Differential updates: download only the files that changed since the installed version.

Why files and not a binary patch
    The app is a folder of a few thousand files. Between two releases almost all of them (Qt, llama.cpp, CUDA
    libraries, Python itself) are byte for byte the same; what changes is the executable and a few small files.
    Comparing whole files needs no patch tool, works from ANY older version (even one that was never released
    with this mechanism) and also repairs damaged or edited files.

How it works
    Release side (tools/prepare_release_assets.py, build_pack() below)
        All files of a build are compressed one by one and written one after another into a "pack", cut into parts of
        < 2 GiB (the GitHub limit):  DiplomaChecker-<platform>-<variant>.pack.001, .002, ...
        DiplomaChecker-<platform>-<variant>.manifest.json lists every file: path, size, SHA-256, mode, and where its
        compressed bytes lie in the pack (offset and length).
    App side (this module)
        1. compute_delta():  hash the installed files (size first) and keep those that equal the manifest.
        2. stage_delta():    hard-link (or copy) the unchanged files into the new folder, then fetch ONLY the bytes
                             of the changed files with HTTP Range requests, unpack and verify each one (SHA-256).
        The result is the same folder the full archive would give, so the swap step is identical.

No Qt here, so it can be tested on its own.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import requests

from common.update_errors import UpdateCancelled, UpdateError

logger = logging.getLogger(__name__)

APP_DIR_NAME = "DiplomaChecker"
PRESERVE = ("models", "logs", "data", ".update")        # top-level entries an update never touches
FORMAT = 1
CHUNK = 1024 * 1024
HASH_CHUNK = 4 * CHUNK
PART_SIZE = 1900 * 1024 * 1024                          # a little under GitHub's 2 GiB per release file
GAP = 512 * 1024                                        # changed files closer than this share one request
REQUEST_TIMEOUT_S = (10, 30)
RETRIES = 3
SPACE_MARGIN = 64 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def pack_name(platform, variant):
    return f"{APP_DIR_NAME}-{platform}-{variant}.pack"


def manifest_name(platform, variant):
    return f"{APP_DIR_NAME}-{platform}-{variant}.manifest.json"


# =========================================================================== release side
class _PartWriter:
    """One logical byte stream written into  base.001, base.002, ...  of at most `part_size` bytes each."""

    def __init__(self, directory, base, part_size):
        self.directory, self.base, self.part_size = Path(directory), base, part_size
        self.parts = []
        self.offset = 0
        self._file = None
        self._in_part = 0

    def write(self, data):
        view = memoryview(data)
        while len(view):
            if self._file is None or self._in_part >= self.part_size:
                self._next()
            piece = view[: self.part_size - self._in_part]
            self._file.write(piece)
            self._in_part += len(piece)
            self.offset += len(piece)
            view = view[len(piece):]

    def _next(self):
        self._finish_part()
        name = f"{self.base}.{len(self.parts) + 1:03d}"
        self._file = open(self.directory / name, "wb")
        self._in_part = 0
        self.parts.append({"name": name, "size": 0})

    def _finish_part(self):
        if self._file is not None:
            self._file.close()
            self.parts[-1]["size"] = self._in_part
            self._file = None

    def close(self):
        if not self.parts:
            self._next()
        self._finish_part()
        return self.parts


def _compressible(head):
    return not head or len(zlib.compress(head, 1)) < 0.9 * len(head)


def _write_file(writer, path):
    sha, raw = hashlib.sha256(), 0
    with open(path, "rb") as f:
        chunk = f.read(CHUNK)
        method = "zlib" if _compressible(chunk) else "store"
        packer = zlib.compressobj(6) if method == "zlib" else None
        while chunk:
            sha.update(chunk)
            raw += len(chunk)
            writer.write(packer.compress(chunk) if packer else chunk)
            chunk = f.read(CHUNK)
        if packer:
            writer.write(packer.flush())
    return method, raw, sha.hexdigest()


def build_pack(package_dir, out_dir, platform, variant, version, part_size=PART_SIZE, log=print):
    """Write the pack parts and the manifest of the build in `package_dir` into `out_dir`. Returns the manifest."""
    package_dir, out_dir = Path(package_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = _PartWriter(out_dir, pack_name(platform, variant), part_size)
    files, links = [], []
    for current, dirs, names in os.walk(package_dir, followlinks=False):
        current = Path(current)
        dirs.sort()
        if current == package_dir:
            dirs[:] = [d for d in dirs if d not in PRESERVE]
            names = [n for n in names if n not in PRESERVE]
        for name in sorted(names) + [d for d in dirs if (current / d).is_symlink()]:
            path = current / name
            rel = path.relative_to(package_dir).as_posix()
            if path.is_symlink():
                links.append({"p": rel, "t": os.readlink(path)})
                continue
            start = writer.offset
            method, size, digest = _write_file(writer, path)
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            files.append({"p": rel, "s": size, "h": digest, "m": mode, "o": start,
                          "c": writer.offset - start, "z": method})
        dirs[:] = [d for d in dirs if not (current / d).is_symlink()]
    parts = writer.close()
    manifest = {"format": FORMAT, "version": str(version), "platform": platform, "variant": variant,
                "parts": parts, "total": writer.offset, "files": files, "links": links}
    (out_dir / manifest_name(platform, variant)).write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    log(f"Pack: {len(files)} files, {len(links)} links, {writer.offset / 1024 / 1024:.1f} MiB in {len(parts)} part(s)")
    return manifest


# =========================================================================== manifest
def _safe_rel(path):
    """True for a relative posix path without '..', drive letters or backslashes, outside the user's data folders."""
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or "\x00" in path:
        return False
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
        return False
    return parts[0] not in PRESERVE


def validate_manifest(manifest):
    """Raise UpdateError('invalid' | 'unsafe') unless the manifest is complete and every path stays inside the app."""
    try:
        if manifest["format"] != FORMAT:
            raise UpdateError("invalid")
        total = int(manifest["total"])
        parts = manifest["parts"]
        if not parts or sum(int(p["size"]) for p in parts) != total:
            raise UpdateError("invalid")
        for p in parts:
            if not re.fullmatch(r"[\w.\-]+", str(p["name"])):
                raise UpdateError("invalid")
        seen = set()
        for e in manifest["files"]:
            if not _safe_rel(e["p"]):
                raise UpdateError("unsafe", name=str(e.get("p")))
            if e["p"] in seen or not _SHA_RE.match(e["h"]) or e["z"] not in ("zlib", "store"):
                raise UpdateError("invalid")
            seen.add(e["p"])
            s, o, c = int(e["s"]), int(e["o"]), int(e["c"])
            if min(s, o, c) < 0 or o + c > total or (e["z"] == "store" and c != s):
                raise UpdateError("invalid")
        for link in manifest["links"]:
            target = PurePosixPath(link["t"])
            joined = os.path.normpath("/".join([str(PurePosixPath(link["p"]).parent), link["t"]]))
            if (not _safe_rel(link["p"]) or target.is_absolute() or "\\" in link["t"]
                    or joined.startswith("..") or link["p"] in seen):
                raise UpdateError("unsafe", name=str(link["p"]))
        tops = {e["p"].split("/")[0] for e in manifest["files"]}
        if not {APP_DIR_NAME, APP_DIR_NAME + ".exe"} & tops or "_internal" not in tops:
            raise UpdateError("invalid")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise UpdateError("invalid") from e
    return manifest


def _join(root, rel):
    return Path(root).joinpath(*rel.split("/"))


# =========================================================================== comparing
@dataclass
class DeltaPlan:
    need: list = field(default_factory=list)        # manifest entries that must be downloaded
    reuse: list = field(default_factory=list)       # [(entry, Path in the installed app)]; Path None = already staged
    groups: list = field(default_factory=list)      # [(start, end, [entries])] ranges of the pack to request
    transfer: int = 0                               # bytes that will be requested (changed files + small gaps)
    raw: int = 0                                    # their size once unpacked
    reused_bytes: int = 0
    done: set = field(default_factory=set)          # paths written by stage_delta (a retry does not repeat them)


def _hash_file(path, cancelled, on_bytes=None):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK):
            if cancelled():
                raise UpdateCancelled()
            digest.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    return digest.hexdigest()


def _same(path, entry, cancelled, on_bytes=None):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_size != entry["s"]:
        return False
    try:
        return _hash_file(path, cancelled, on_bytes) == entry["h"]
    except OSError:
        return False


def make_groups(entries, gap=GAP):
    """Ranges of the pack to request: neighbouring files closer than `gap` bytes share one request."""
    groups = []
    for e in sorted((e for e in entries if e["c"] > 0), key=lambda e: e["o"]):
        if groups and e["o"] - groups[-1][1] <= gap:
            groups[-1][1] = e["o"] + e["c"]
            groups[-1][2].append(e)
        else:
            groups.append([e["o"], e["o"] + e["c"], [e]])
    return [(a, b, es) for a, b, es in groups]


def compute_delta(manifest, install_root, new_root, progress=lambda d, t: None, cancelled=lambda: False):
    """Which files of `manifest` are already here (in the installed app or in a half-finished staging folder)?
    progress(done_bytes, total_bytes) while hashing."""
    entries = manifest["files"]
    total = sum(e["s"] for e in entries) or 1
    done = 0
    plan = DeltaPlan()
    last = [0.0]

    def tick(n):
        nonlocal done
        done += n
        now = time.monotonic()
        if now - last[0] > 0.1:
            last[0] = now
            progress(min(done, total), total)

    for e in entries:
        if cancelled():
            raise UpdateCancelled()
        before = done
        staged, installed = _join(new_root, e["p"]), _join(install_root, e["p"])
        if _same(staged, e, cancelled, tick):
            plan.reuse.append((e, None))
        elif _same(installed, e, cancelled, tick):
            plan.reuse.append((e, installed))
            plan.reused_bytes += e["s"]
        else:
            plan.need.append(e)
            plan.raw += e["s"]
        done = before + e["s"]                      # count the file fully even when it was skipped by size
    progress(total, total)
    plan.groups = make_groups(plan.need)
    plan.transfer = sum(b - a for a, b, _ in plan.groups)
    return plan


# =========================================================================== fetching
class _Stream:
    """Reads bytes [start, end) of the pack, which lies in several release files, with HTTP Range requests."""

    def __init__(self, parts, start, end, cancelled, on_bytes, user_agent):
        self._cancelled, self._on_bytes, self._ua = cancelled, on_bytes, user_agent
        self._buffer = b""
        self._iter = self._chunks(parts, start, end)

    def _chunks(self, parts, start, end):
        base = 0
        for part in parts:
            size = int(part["size"])
            lo, hi = max(start, base), min(end, base + size)
            if lo < hi:
                yield from self._segment(part, lo - base, hi - base)
            base += size

    def _segment(self, part, first, stop):
        """Bytes [first, stop) of one release file; resumes after a dropped connection."""
        pos, attempts = first, 0
        while pos < stop:
            headers = {"User-Agent": self._ua, "Range": f"bytes={pos}-{stop - 1}"}
            try:
                with requests.get(part["url"], headers=headers, stream=True, timeout=REQUEST_TIMEOUT_S) as r:
                    if r.status_code == 200 and pos == 0:
                        pass                        # the whole file is sent: fine, we stop at `stop`
                    elif r.status_code != 206:
                        if r.status_code == 200:
                            raise UpdateError("range")
                        raise UpdateError("http", status=r.status_code)
                    for chunk in r.iter_content(CHUNK):
                        if self._cancelled():
                            raise UpdateCancelled()
                        chunk = chunk[: stop - pos]
                        if not chunk:
                            break
                        pos += len(chunk)
                        self._on_bytes(len(chunk))
                        yield chunk
                        if pos >= stop:
                            break
            except requests.RequestException as e:
                attempts += 1
                if attempts > RETRIES:
                    raise UpdateError("network", error=str(e)) from e
                time.sleep(1.5 * attempts)
                continue
            if pos < stop:                          # the server closed early
                attempts += 1
                if attempts > RETRIES:
                    raise UpdateError("size", name=part["name"])

    def read(self, n):
        while len(self._buffer) < n:
            try:
                self._buffer += next(self._iter)
            except StopIteration:
                raise UpdateError("size", name="pack") from None
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def skip(self, n):
        while n > 0:
            n -= len(self.read(min(n, CHUNK)))


def _inflate(decompressor, chunk):
    yield decompressor.decompress(chunk, 4 * CHUNK)
    while decompressor.unconsumed_tail:
        yield decompressor.decompress(decompressor.unconsumed_tail, 4 * CHUNK)


def _extract(stream, entry, new_root):
    dest = _join(new_root, entry["p"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    digest, raw, left = hashlib.sha256(), 0, entry["c"]
    unpacker = zlib.decompressobj() if entry["z"] == "zlib" else None
    try:
        with open(tmp, "wb") as out:
            def put(data):
                nonlocal raw
                raw += len(data)
                if raw > entry["s"]:
                    raise UpdateError("checksum")
                digest.update(data)
                out.write(data)

            while left:
                chunk = stream.read(min(CHUNK, left))
                left -= len(chunk)
                if unpacker:
                    try:
                        for data in _inflate(unpacker, chunk):
                            put(data)
                    except zlib.error as e:
                        raise UpdateError("checksum") from e
                else:
                    put(chunk)
            if unpacker:
                put(unpacker.flush())
        if raw != entry["s"] or digest.hexdigest() != entry["h"]:
            raise UpdateError("checksum")
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if sys.platform != "win32":
        os.chmod(dest, entry["m"])


def _free_bytes(path):
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _link_or_copy(src, dst, hard):
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    if hard:
        try:
            os.link(src, dst)
            return True
        except OSError:
            pass
    shutil.copy2(src, dst)
    return False


def _prune(new_root, manifest):
    """Remove everything in the staging folder that is not part of this release (left by an older, unfinished one)."""
    keep_files = {e["p"] for e in manifest["files"]} | {l["p"] for l in manifest["links"]}
    keep_dirs = set()
    for p in keep_files:
        parts = p.split("/")
        keep_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    for current, dirs, names in os.walk(new_root, topdown=True, followlinks=False):
        rel_dir = Path(current).relative_to(new_root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        for name in list(dirs):
            path = Path(current) / name
            rel = rel_dir + name
            if path.is_symlink():
                dirs.remove(name)
                if rel not in keep_files:
                    path.unlink()
            elif rel not in keep_dirs:
                shutil.rmtree(path, ignore_errors=True)
                dirs.remove(name)
        for name in names:
            if rel_dir + name not in keep_files:
                (Path(current) / name).unlink(missing_ok=True)


def stage_delta(manifest, plan, parts, new_root, progress, cancelled, user_agent="DiplomaChecker-updater",
                progress_link=lambda d, t: None):
    """Build the new app folder `new_root` (= .update/new/DiplomaChecker): unchanged files linked from the installed
    app, changed ones fetched. `parts`: [{"name", "size", "url"}] of the pack in order.
    progress(done_bytes, total_bytes) counts the bytes requested from the server."""
    new_root = Path(new_root)
    new_root.mkdir(parents=True, exist_ok=True)
    for stale in new_root.rglob("*.part"):
        stale.unlink(missing_ok=True)

    # --- room: changed files, plus copies of the unchanged ones when the disk cannot hard-link
    from_install = [(e, src) for e, src in plan.reuse if src is not None]
    hard = True
    if from_install:
        probe = new_root / ".link_probe"
        probe.unlink(missing_ok=True)
        try:
            os.link(from_install[0][1], probe)
        except OSError:
            hard = False
        finally:
            probe.unlink(missing_ok=True)
    remaining = sum(e["s"] for e in plan.need if e["p"] not in plan.done)
    need = int(remaining * 1.15) + SPACE_MARGIN + (0 if hard else sum(e["s"] for e, _ in from_install))
    free = _free_bytes(new_root)
    if free < need:
        raise UpdateError("space", free=free, needed=need)

    # --- folders, links, unchanged files
    for e in manifest["files"]:
        _join(new_root, e["p"]).parent.mkdir(parents=True, exist_ok=True)
    for link in manifest["links"]:
        path = _join(new_root, link["p"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink() if (path.is_symlink() or path.is_file()) else shutil.rmtree(path)
        try:
            os.symlink(link["t"], path)
        except OSError as e:
            raise UpdateError("invalid") from e
    for i, (e, src) in enumerate(from_install):
        if cancelled():
            raise UpdateCancelled()
        _link_or_copy(src, _join(new_root, e["p"]), hard)
        progress_link(i + 1, len(from_install))
    for e in manifest["files"]:                     # empty files carry no bytes in the pack
        if e["s"] == 0 and not _join(new_root, e["p"]).is_file():
            _join(new_root, e["p"]).write_bytes(b"")

    # --- changed files
    pending = [(a, b, [e for e in es if e["p"] not in plan.done]) for a, b, es in plan.groups]
    pending = [(a, b, es) for a, b, es in pending if es]
    transfer = sum(b - a for a, b, _ in pending) or 1
    sent = 0

    def on_bytes(n):
        nonlocal sent
        sent += n
        progress(min(sent, transfer), transfer)

    progress(0, transfer)
    for a, b, entries in pending:
        stream = _Stream(parts, a, b, cancelled, on_bytes, user_agent)
        position = a
        for e in entries:
            stream.skip(e["o"] - position)
            _extract(stream, e, new_root)
            plan.done.add(e["p"])
            position = e["o"] + e["c"]
        stream.skip(b - position)

    _prune(new_root, manifest)
    for e in manifest["files"]:                     # last look: everything is there with the right size
        path = _join(new_root, e["p"])
        if not path.is_file() or path.stat().st_size != e["s"]:
            raise UpdateError("invalid")

# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# collect_* import our own packages, so src/ must be importable (also in the isolated child).
SRC = os.path.join(SPECPATH, "src")
sys.path.insert(0, SRC)
os.environ["PYTHONPATH"] = SRC + os.pathsep + os.environ.get("PYTHONPATH", "")

datas = [("src/ui/assets", "ui/assets")]
binaries = []
hiddenimports = []


def add_all(pkg):
    if importlib.util.find_spec(pkg) is None:
        print(f"[spec] optional package not installed, skipping: {pkg}")
        return
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Always required
for pkg in ("spacy", "pl_core_news_lg", "en_core_web_lg", "morfeusz2",
            "lingua", "spellchecker", "language_tool_python"):
    add_all(pkg)

# Optional AI runtime (extras cpu/gpu). llama_cpp loads its shared libs via ctypes,
# so PyInstaller only ships them thanks to collect_all.
for pkg in ("llama_cpp", "sentence_transformers"):
    add_all(pkg)

# Our own code
hiddenimports += collect_submodules("analysis")
hiddenimports += collect_submodules("ui")
hiddenimports += collect_submodules("common")
hiddenimports += collect_submodules("app", filter=lambda n: n != "app.main")
datas += collect_data_files("analysis")

# _internal/VERSION.txt: the APP_VERSION this build was made from. tools/prepare_release_assets.py compares it with
# the release tag, so a build of an old version cannot be published under a new tag.
import re
with open(os.path.join(SRC, "common", "version.py"), encoding="utf-8") as _f:
    _version = re.search(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", _f.read(), re.M).group(1)
_version_file = os.path.join(workpath, "VERSION.txt")
os.makedirs(workpath, exist_ok=True)
with open(_version_file, "w", encoding="utf-8") as _f:
    _f.write(_version + "\n")
datas.append((_version_file, "."))
print(f"[spec] building version {_version}")

a = Analysis(
    ["src/app/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DiplomaChecker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="DiplomaChecker",
)
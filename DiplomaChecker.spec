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
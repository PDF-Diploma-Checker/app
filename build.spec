from pathlib import Path

PROJECT_ROOT = Path(SPECPATH)
SRC_DIR = PROJECT_ROOT / "src"

datas = [
    (str(SRC_DIR), "src"),
    (str(SRC_DIR / "ui"), "ui"),
    (str(SRC_DIR / "common"), "common"),
    (str(SRC_DIR / "analysis"), "analysis"),
    (str(PROJECT_ROOT / "docs" / "app-configs"), "."),
]

a = Analysis(
    [str(SRC_DIR / "app" / "main.py")],
    pathex=[
        str(SRC_DIR),
        str(SRC_DIR / "ui"),
        str(SRC_DIR / "app"),
        str(SRC_DIR / "common"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DiplomaChecker",
)

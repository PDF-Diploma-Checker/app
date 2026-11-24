"""List the Python modules a finished build holds, so that a later release can tell whether new code can be patched in.

Usage:  python tools/list_bundled_modules.py dist/gpu/DiplomaChecker --platform linux --variant gpu --out release_files

Writes DiplomaChecker-<platform>-<variant>.modules.json: the modules in the archive of the executable (PyInstaller's
PYZ: the pure Python ones), those in base_library.zip, and the compiled ones that lie in _internal as files. A release
that changes only our code (tools/release_plan.py) may import a module only when it is in this list; otherwise the
build has to be made again. Needs PyInstaller, which the build environments have.
"""

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

APP = "DiplomaChecker"
COMPILED = (".so", ".pyd", ".dylib")


def _module_from_path(rel):
    """'PySide6/QtWidgets.abi3.so' -> 'PySide6.QtWidgets', 'pkg/__init__.py' -> 'pkg'; None for what is no module."""
    parts = list(Path(rel).parts)
    parts[-1] = parts[-1].split(".")[0]
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def bundled_module_names(build_dir):
    """Sorted names of the modules of the build in `build_dir` (the folder with the executable and _internal/)."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    build_dir = Path(build_dir)
    exe = next((build_dir / name for name in (APP + ".exe", APP) if (build_dir / name).is_file()), None)
    if exe is None:
        raise FileNotFoundError(f"no {APP} executable in {build_dir}")
    names = set()
    archive = CArchiveReader(str(exe))
    for entry in archive.toc:
        if entry.endswith(".pyz"):
            with tempfile.TemporaryDirectory() as folder:
                pyz = Path(folder) / "app.pyz"
                pyz.write_bytes(archive.extract(entry))
                names.update(ZlibArchiveReader(str(pyz)).toc)
    internal = build_dir / "_internal"
    library = internal / "base_library.zip"
    if library.is_file():
        for name in zipfile.ZipFile(library).namelist():
            module = _module_from_path(name)
            if module:
                names.add(module)
    for path in internal.rglob("*"):
        if path.is_file() and (path.suffix in COMPILED or path.suffix == ".py"):
            module = _module_from_path(path.relative_to(internal).as_posix())
            if module:
                names.add(module)
    return sorted(names)


def modules_name(platform, variant):
    return f"{APP}-{platform}-{variant}.modules.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("build", type=Path, help="the build folder (with the executable and _internal/)")
    ap.add_argument("--platform", choices=("windows", "linux"), required=True)
    ap.add_argument("--variant", choices=("base", "cpu", "gpu"), required=True)
    ap.add_argument("--out", type=Path, default=Path("release_files"))
    args = ap.parse_args(argv)
    names = bundled_module_names(args.build)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / modules_name(args.platform, args.variant)
    target.write_text(json.dumps({"format": 1, "platform": args.platform, "variant": args.variant, "modules": names},
                                 separators=(",", ":")), encoding="utf-8")
    print(f"{target}: {len(names)} modules")


if __name__ == "__main__":
    sys.exit(main())

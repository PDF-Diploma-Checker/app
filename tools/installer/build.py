"""Build the installer of this system into dist/installer. PyInstaller makes a file only for the system it runs on.

Usage: uvx --with requests --with pyinstaller python tools/installer/build.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    system = "windows" if sys.platform == "win32" else "linux"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", f"DiplomaChecker-Installer-{system}",
        "--paths", str(ROOT / "src"), "--paths", str(HERE),
        "--add-data", f"{ROOT / 'src' / 'ui' / 'assets' / 'logo.png'}{os.pathsep}.",
        "--distpath", str(ROOT / "dist" / "installer"),
        "--workpath", str(ROOT / "build" / "installer"),
        "--specpath", str(ROOT / "build" / "installer"),
        str(HERE / "installer.py"),
    ], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()

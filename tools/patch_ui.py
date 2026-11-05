"""Put the current UI code into finished builds, without building them again. For a release that changes only src/ui.

Usage (run it on every platform, with the builds of that platform in dist/):

    1. Change src/ui and set the new number in src/common/version.py and pyproject.toml.
    2. python tools/patch_ui.py --since v0.4.1
    3. python tools/publish_release.py --tag v0.4.2

--since is the commit the builds in dist/ were made from: the script stops when anything outside src/ui (apart from the
version number) changed since then, because such a change needs a full build. Users get the new files in kilobytes
through the differential update, but publishing still packs and uploads whole packages.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_UI = ROOT / "src" / "ui"
VERSION_FILE = ROOT / "src" / "common" / "version.py"
VARIANTS = ("base", "cpu", "gpu")
ALLOWED = ("src/ui/", "src/common/version.py", "pyproject.toml", "uv.lock", "tools/", "unit_tests/", "README.md")


def changed_outside_ui(since):
    """Files changed since `since`, in the last commits and in the working tree, that a patch cannot carry."""
    output = subprocess.run(["git", "diff", "--name-only", since], cwd=ROOT, check=True, capture_output=True,
                            text=True).stdout
    return [name for name in output.split("\n") if name and not name.startswith(ALLOWED)]


def app_version():
    match = re.search(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", VERSION_FILE.read_text(encoding="utf-8"), re.M)
    if not match:
        sys.exit("APP_VERSION not found in src/common/version.py")
    return match.group(1)


def patch_build(app_dir, version):
    """Replace the UI code and the version of one build. A build made before the UI became plain files has no such
    files, and code copied next to it would be ignored."""
    internal = app_dir / "_internal"
    target = internal / "ui"
    if not any(target.glob("*.py")) or not (internal / "common" / "version.py").is_file():
        sys.exit(f"{app_dir}: no UI code as plain files, this build needs a full rebuild")
    for old in target.rglob("*.py"):
        old.unlink()
    for new in SRC_UI.rglob("*.py"):
        destination = target / new.relative_to(SRC_UI)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new, destination)
    shutil.copy2(VERSION_FILE, internal / "common" / "version.py")
    (internal / "VERSION.txt").write_text(version, encoding="utf-8")
    print(f"  {app_dir}: UI code updated, version {version}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", required=True, help="the commit or tag the builds in dist/ were made from")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)

    blocked = changed_outside_ui(args.since)
    if blocked:
        sys.exit("These changes need a full build:\n  " + "\n  ".join(blocked))

    builds = [args.dist / variant / "DiplomaChecker" for variant in VARIANTS]
    builds = [build for build in builds if build.is_dir()]
    if not builds:
        sys.exit(f"No builds in {args.dist}")
    version = app_version()
    for build in builds:
        patch_build(build, version)


if __name__ == "__main__":
    main()

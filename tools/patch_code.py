"""Put the current code into finished builds, without building them again. For a release that changes only our code.

Usage (run it on every platform, with the builds of that platform in dist/):

    1. Change the code in src/ and set the new number in src/common/version.py and pyproject.toml.
    2. python tools/patch_code.py --since v0.4.1
    3. python tools/publish_release.py --tag v0.4.2

--since is the commit the builds in dist/ were made from. The script stops when a change needs a full build: other
libraries, an import of a module that is not in the package, new data files, the launcher or the build files.
Users get the new files in kilobytes through the differential update, but publishing still packs and uploads whole
packages.
"""

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "common" / "version.py"
VARIANTS = ("base", "cpu", "gpu")
OWN_PACKAGES = ("analysis", "app", "common", "ui")
LAUNCHER = "src/app/launcher.py"
IGNORED = ("dictionary_service/", "tools/", "unit_tests/", "docs/", ".github/", "README.md", "setup_guide.md")
VERSION_ONLY = ("pyproject.toml", "uv.lock")


def git(*args):
    # utf-8: the sources hold Polish letters, and on Windows text mode would read them in the local code page
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, encoding="utf-8",
                          errors="replace").stdout


def changed_files(since):
    """[(status, path)] of everything changed since `since`, in the last commits and in the working tree."""
    rows = (line.split("\t") for line in git("diff", "--name-status", "--no-renames", since).splitlines())
    return [(status, path) for status, path in rows]


def external_imports(source):
    """Names of the modules outside our code imported anywhere in this Python source."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return {name for name in names if name.split(".")[0] not in OWN_PACKAGES}


def bundled_modules(since):
    """Modules our code imported at `since`: PyInstaller put them into the build."""
    names = set()
    for path in git("ls-tree", "-r", "--name-only", since, "src").splitlines():
        if path.endswith(".py"):
            try:
                names |= external_imports(git("show", f"{since}:{path}"))
            except SyntaxError:
                continue
    return names


def needs_full_build(since, changes):
    """Why these changes cannot be patched into a build (a module that is not in it would only fail on the user's
    computer)."""
    reasons = []
    bundled = None
    for status, path in changes:
        if path.startswith(IGNORED):
            continue
        if path in VERSION_ONLY:
            lines = git("diff", "--unified=0", since, "--", path).splitlines()
            if any(line[0] in "+-" and not line.startswith(("+++", "---", "+version = ", "-version = "))
                   for line in lines if line):
                reasons.append(f"{path}: more than the version changed")
        elif status == "M" and path.startswith("src/") and path.endswith(".txt"):
            continue                    # a list of words: the build reads the file, a new copy just replaces it
        elif not path.startswith("src/") or path == LAUNCHER or not path.endswith(".py"):
            reasons.append(path)
        elif status != "D":
            if bundled is None:
                bundled = bundled_modules(since)
            # a module built into the interpreter is in every build, whatever our code imported at `since`
            new = external_imports((ROOT / path).read_text(encoding="utf-8")) - bundled - set(sys.builtin_module_names)
            if new:
                reasons.append(f"{path}: new imports {', '.join(sorted(new))}")
    return reasons


def app_version():
    match = re.search(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", VERSION_FILE.read_text(encoding="utf-8"), re.M)
    if not match:
        sys.exit("APP_VERSION not found in src/common/version.py")
    return match.group(1)


def patch_build(app_dir, changes, version):
    """Change the code files of one build. A build made before our code became plain files has no such files, and
    code copied next to it would be ignored."""
    internal = app_dir / "_internal"
    if not all((internal / package / "__init__.py").is_file() or any((internal / package).glob("*.py"))
               for package in OWN_PACKAGES):
        sys.exit(f"{app_dir}: no code as plain files, this build needs a full rebuild")
    for status, path in changes:
        if not path.startswith("src/"):
            continue
        destination = internal / Path(path).relative_to("src")
        if status == "D":
            destination.unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, destination)
    (internal / "VERSION.txt").write_text(version + "\n", encoding="utf-8")
    print(f"  {app_dir}: code updated, version {version}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", required=True, help="the commit or tag the builds in dist/ were made from")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)

    try:
        changes = changed_files(args.since)
    except subprocess.CalledProcessError as e:
        sys.exit(f"git does not know {args.since}. Run: git fetch origin --tags\n{e.stderr}")
    blocked = needs_full_build(args.since, changes)
    if blocked:
        sys.exit("These changes need a full build:\n  " + "\n  ".join(blocked))

    builds = [args.dist / variant / "DiplomaChecker" for variant in VARIANTS]
    builds = [build for build in builds if build.is_dir()]
    if not builds:
        sys.exit(f"No builds in {args.dist}")
    version = app_version()
    for build in builds:
        patch_build(build, changes, version)


if __name__ == "__main__":
    main()

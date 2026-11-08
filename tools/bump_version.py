"""Raise the last number of the version by one: 0.4.2 -> 0.4.3. Prints the new version.

.github/workflows/bump_version.yml runs it after each merge to main, with the commits before and after the merge.
A merge that changes the version itself keeps it: 0.5.0 set for a full build must not become 0.5.1.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VERSION = r"\d+\.\d+\.(\d+)"
PLACES = {
    "src/common/version.py": rf'^APP_VERSION = "({_VERSION})"',
    "pyproject.toml": rf'^version = "({_VERSION})"',
    "uv.lock": rf'^name = "pdf-diploma-checker"\nversion = "({_VERSION})"',
}


def next_version(version):
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def version_at(commit, root=ROOT):
    """The version in a commit, None when git does not know the commit (the first push of a branch)."""
    shown = subprocess.run(["git", "show", f"{commit}:src/common/version.py"], cwd=root, capture_output=True,
                           encoding="utf-8")
    match = re.search(PLACES["src/common/version.py"], shown.stdout, re.M) if shown.returncode == 0 else None
    return match.group(1) if match else None


def set_by_hand(before, after, root=ROOT):
    """True when the commits between `before` and `after` changed the version."""
    old = version_at(before, root)
    return old is not None and old != version_at(after, root)


def bump(root=ROOT):
    """Write the next version to every place that holds it and return it. The places must agree."""
    edits, found = {}, set()
    for name, pattern in PLACES.items():
        path = Path(root) / name
        text = path.read_text(encoding="utf-8")
        match = re.search(pattern, text, re.M)
        if not match:
            sys.exit(f"No version found in {name}")
        found.add(match.group(1))
        edits[path] = text[:match.start(1)] + next_version(match.group(1)) + text[match.end(1):]
    if len(found) != 1:
        sys.exit(f"The files hold different versions: {sorted(found)}")
    for path, text in edits.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    return next_version(found.pop())


if __name__ == "__main__":
    if len(sys.argv) == 3 and set_by_hand(*sys.argv[1:]):
        sys.exit(0)
    print(bump())

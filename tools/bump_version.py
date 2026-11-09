"""Keep the version one above the newest release: 0.4.2 released -> 0.4.3. Prints the version when it changed.

.github/workflows/bump_version.yml runs it after each merge to main, with the commits before and after the merge and
the tag of the newest release. Merges before the next release share one version, so numbers are not used up.
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


def target_version(current, latest):
    """The version after release `latest`. A higher first or second number was set for a full build and waits for it."""
    if [int(n) for n in current.split(".")[:2]] > [int(n) for n in latest.split(".")[:2]]:
        return current
    return next_version(latest)


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


def bump(latest, root=ROOT):
    """Write the version after release `latest` to every place that holds it and return it, None when it is already
    there. The places must agree."""
    matches, found = {}, set()
    for name, pattern in PLACES.items():
        path = Path(root) / name
        text = path.read_text(encoding="utf-8")
        match = re.search(pattern, text, re.M)
        if not match:
            sys.exit(f"No version found in {name}")
        found.add(match.group(1))
        matches[path] = (text, match)
    if len(found) != 1:
        sys.exit(f"The files hold different versions: {sorted(found)}")
    current = found.pop()
    target = target_version(current, latest.lstrip("vV"))
    if target == current:
        return None
    for path, (text, match) in matches.items():
        path.write_text(text[:match.start(1)] + target + text[match.end(1):], encoding="utf-8", newline="\n")
    return target


if __name__ == "__main__":
    before, after, newest = sys.argv[1:]
    if not set_by_hand(before, after):
        print(bump(newest) or "")

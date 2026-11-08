"""Raise the last number of the version by one: 0.4.2 -> 0.4.3. Prints the new version.

.github/workflows/bump_version.yml runs it after each merge to main.
"""

import re
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
    print(bump())

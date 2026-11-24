"""Check a release (a draft too) before it is published: every platform and variant has a manifest of this version,
and every part of every pack that a manifest points to exists, in the right release, with the right size.

Usage:  python tools/verify_release.py --tag v0.6.8        (exit code 1 when something is wrong)

A patch release holds only its own new parts; the others stay in the older releases, so those are checked too.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import publish_release as publish  # noqa: E402
from common import delta  # noqa: E402
from common.update_check import GITHUB_REPO  # noqa: E402

PLATFORMS = ("linux", "windows")
VARIANTS = ("base", "cpu", "gpu")


def release_assets(repo, tag, cache):
    if tag not in cache:
        release = publish.find_release(repo, tag)
        cache[tag] = {a["name"]: a["size"] for a in (release or {}).get("assets", [])} if release else None
    return cache[tag]


def verify(repo, tag, platforms=PLATFORMS, variants=VARIANTS):
    """A list of problems (empty: the release is complete and consistent)."""
    problems, cache = [], {}
    own = release_assets(repo, tag, cache)
    if own is None:
        return [f"release {tag} does not exist"]
    version = tag.lstrip("vV")
    with tempfile.TemporaryDirectory() as folder:
        for platform in platforms:
            for variant in variants:
                name = delta.manifest_name(platform, variant)
                label = f"{platform}-{variant}"
                if name not in own:
                    problems.append(f"{label}: no manifest in {tag}")
                    continue
                target = Path(folder) / name
                publish.gh("release", "download", tag, "-R", repo, "-p", name, "-O", str(target), "--clobber")
                try:
                    manifest = delta.validate_manifest(json.loads(target.read_text(encoding="utf-8")))
                except Exception as error:
                    problems.append(f"{label}: invalid manifest ({error})")
                    continue
                if manifest["version"] != version:
                    problems.append(f"{label}: manifest of {manifest['version']}, not {version}")
                for part in manifest["parts"]:
                    where = part.get("release") or tag
                    assets = release_assets(repo, where, cache)
                    size = (assets or {}).get(part["name"])
                    if size != part["size"]:
                        problems.append(f"{label}: {part['name']} in {where} has {size} bytes, expected {part['size']}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--repo", default=GITHUB_REPO)
    args = ap.parse_args(argv)
    problems = verify(args.repo, args.tag)
    for problem in problems:
        print("PROBLEM:", problem)
    if problems:
        sys.exit(1)
    print(f"{args.tag}: all {len(PLATFORMS) * len(VARIANTS)} platform/variant manifests are complete and consistent")


if __name__ == "__main__":
    main()

"""Publish a release with only the files that changed, without packing whole packages again.

Usage (on every platform, after tools/patch_code.py put the code into the builds in dist/):

    python tools/publish_patch.py --tag v0.4.2 --base v0.4.1

The manifest of --base says what each file of the builds was. Files that differ go into a small pack of this release;
the new manifest points to the pack parts of the older releases for the others, so those releases have to stay
published. It uploads to a DRAFT and has to be published by hand, when all platforms are there.

An app older than 0.4.1 cannot read such a release, and a first install needs a full archive: the download page offers
the newest release that has one, and the app updates from there.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import json  # noqa: E402

import publish_release as publish  # noqa: E402
from common import delta  # noqa: E402
from common.update_check import GITHUB_REPO  # noqa: E402

MAX_PATCH_MIB = 300     # more means the build in dist/ is not the build of --base


def base_manifest(repo, tag, platform, variant, directory):
    """The manifest of the older release: a local copy of it, or else from GitHub."""
    name = delta.manifest_name(platform, variant)
    local = ROOT / "release_files" / tag / name
    if not local.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        local = directory / name
        try:
            publish.gh("release", "download", tag, "-R", repo, "-p", name, "-O", str(local), "--clobber")
        except RuntimeError as e:
            sys.exit(f"{name} of {tag} is not available, publish {platform}-{variant} there first: {e}")
    return delta.validate_manifest(json.loads(local.read_text(encoding="utf-8")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="tag of this release, e.g. v0.4.2")
    ap.add_argument("--base", required=True, help="tag of the release the builds in dist/ were made for, e.g. v0.4.1")
    ap.add_argument("--repo", default=GITHUB_REPO)
    ap.add_argument("--out", type=Path, default=ROOT / "release_files")
    ap.add_argument("--only", choices=publish.VARIANTS, action="append", help="only these variants (repeatable)")
    ap.add_argument("--no-upload", action="store_true", help="only pack, do not touch GitHub")
    ap.add_argument("--max-mib", type=int, default=MAX_PATCH_MIB, help="stop when the changed files take more than this")
    args = ap.parse_args(argv)

    version = args.tag.lstrip("vV")
    builds = [b for b in publish.find_builds([]) if not args.only or b[2] in args.only]
    if not builds:
        sys.exit("No builds found in dist/")
    out = args.out / args.tag
    uploads = {}
    for folder, platform, variant in builds:
        built = (folder / "_internal" / "VERSION.txt").read_text(encoding="utf-8").strip()
        if built != version:
            sys.exit(f"{folder} has version {built}, not {version}: run tools/patch_code.py first")
        print(f"\n=== {platform}-{variant}: {folder}")
        old = base_manifest(args.repo, args.base, platform, variant, out / "base")
        manifest, changed = delta.build_patch_pack(folder, out, platform, variant, version, old, args.base)
        for path in changed[:40]:
            print(f"  {path}")
        new_parts = [part for part in manifest["parts"] if "release" not in part]
        size = sum(part["size"] for part in new_parts) / 1024 / 1024
        if size > args.max_mib:
            sys.exit(f"{size:.0f} MiB changed: dist/ does not hold the build of {args.base}. Use --max-mib if it should.")
        uploads[(platform, variant)] = [out / part["name"] for part in new_parts] + [out / delta.manifest_name(platform, variant)]
    if args.no_upload:
        return

    release = publish.ensure_release(args.repo, args.tag)
    online = {a["name"]: a for a in release.get("assets", [])}
    for (platform, variant), files in uploads.items():
        prefix = f"{delta.APP_DIR_NAME}-{platform}-{variant}."
        names = {f.name for f in files}
        for name in sorted(n for n in online if n.startswith(prefix) and n not in names):
            print(f"  removing old {name}")
            publish.gh("release", "delete-asset", args.tag, name, "-R", args.repo, "--yes")
        for path in files:
            have = online.get(path.name)
            if have and have.get("digest") == publish.sha256_of(path):
                print(f"  {path.name}: already uploaded")
                continue
            print(f"  uploading {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MiB)")
            publish.upload(args.repo, args.tag, path)
    print(f"\nUploaded to the draft {args.tag}. Publish it when every platform is there.")


if __name__ == "__main__":
    main()

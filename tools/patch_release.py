"""Make a patch release from the base release alone: no build, no download of the packages.

Usage (the release workflow runs it for the variants that tools/release_plan.py chose to patch; gh must be logged in
with a token that can write to the download repository):

    python tools/patch_release.py --tag v0.6.8 --base v0.6.7 --since <commit of v0.6.7> --variants linux-base,windows-gpu

The manifest of the base release lists every file of a build with its hash and where it lies in the pack. The files
that changed in src/ since the base (tools/patch_code.py decides which) are packed into a small new part, the new
manifest points to the pack parts of the older releases for everything else. Uploads to the DRAFT of --tag; the
list of modules of every variant is carried over to it, so the next release can be planned from this one.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import json  # noqa: E402

import patch_code  # noqa: E402
import publish_release as publish  # noqa: E402
from common import delta  # noqa: E402
from common.update_check import GITHUB_REPO  # noqa: E402
from list_bundled_modules import modules_name  # noqa: E402


def code_changes(since):
    """([(src path, status)] changed or new, [paths of the package that are gone]) since `since`."""
    changed, removed = [], []
    for status, path in patch_code.changed_files(since):
        if not path.startswith("src/"):
            continue
        relative = "_internal/" + Path(path).relative_to("src").as_posix()
        if status == "D":
            removed.append(relative)
        else:
            changed.append((path, relative))
    return changed, removed


def overrides_tree(folder, changed, version):
    """The files of the patch, laid out as in the package (the code lies in _internal/)."""
    for source, relative in changed:
        target = Path(folder) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)
        target.chmod(0o644)
    version_file = Path(folder) / "_internal" / "VERSION.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(version + "\n", encoding="utf-8")
    version_file.chmod(0o644)


def base_manifest(repo, tag, platform, variant, directory):
    name = delta.manifest_name(platform, variant)
    directory.mkdir(parents=True, exist_ok=True)
    publish.gh("release", "download", tag, "-R", repo, "-p", name, "-O", str(directory / name), "--clobber")
    return delta.validate_manifest(json.loads((directory / name).read_text(encoding="utf-8")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="the release to make, e.g. v0.6.8 (equals APP_VERSION)")
    ap.add_argument("--base", required=True, help="the release it is a patch of")
    ap.add_argument("--since", required=True, help="the commit the builds of the base release were made from")
    ap.add_argument("--variants", required=True, help="comma separated: linux-base,windows-gpu,...")
    ap.add_argument("--repo", default=GITHUB_REPO)
    ap.add_argument("--out", type=Path, default=ROOT / "release_files")
    ap.add_argument("--no-upload", action="store_true", help="only make the files, do not touch GitHub")
    args = ap.parse_args(argv)

    version = args.tag.lstrip("vV")
    if version != patch_code.app_version():
        sys.exit(f"{args.tag} is not APP_VERSION ({patch_code.app_version()})")
    wanted = [item.strip() for item in args.variants.split(",") if item.strip()]
    changed, removed = code_changes(args.since)
    print(f"{len(changed)} files changed, {len(removed)} removed since {args.since}")
    out = args.out / args.tag
    uploads = {}
    with tempfile.TemporaryDirectory() as folder:
        tree = Path(folder) / "patch"
        overrides_tree(tree, changed, version)
        for key in wanted:
            platform, variant = key.split("-")
            print(f"\n=== {key}")
            old = base_manifest(args.repo, args.base, platform, variant, out / "base")
            manifest, _ = delta.build_patch_from_overrides(tree, removed, out, platform, variant, version, old, args.base)
            new_parts = [part for part in manifest["parts"] if "release" not in part]
            size = sum(part["size"] for part in new_parts) / 1024 / 1024
            if size > 300:
                sys.exit(f"{size:.0f} MiB changed: this is not a patch, make a full build")
            files = [out / part["name"] for part in new_parts] + [out / delta.manifest_name(platform, variant)]
            modules = out / modules_name(platform, variant)
            publish.gh("release", "download", args.base, "-R", args.repo, "-p", modules.name, "-O", str(modules),
                       "--clobber")
            uploads[key] = files + [modules]
    if args.no_upload:
        return

    release = publish.ensure_release(args.repo, args.tag)
    online = {asset["name"]: asset for asset in release.get("assets", [])}
    for key, files in uploads.items():
        prefix = f"{delta.APP_DIR_NAME}-{key}."
        names = {path.name for path in files}
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
    print(f"\nUploaded to the draft {args.tag}.")


if __name__ == "__main__":
    main()

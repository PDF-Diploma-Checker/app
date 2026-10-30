"""Pack the built variants and upload them to the GitHub release used by the in-app updater - no Google Drive needed.

Usage (needs the GitHub CLI `gh`, logged in with push rights to the download repository):

    python tools/publish_release.py --tag v0.3.1                  # pack + upload every build found in dist/
    python tools/publish_release.py --tag v0.3.1 --publish        # ... and make the release public at the end
    python tools/publish_release.py --tag v0.3.1 --dist D:\\builds\\gpu\\DiplomaChecker   # a build elsewhere

Big builds (the Windows/Linux gpu variant) are no problem: tools/prepare_release_assets.py cuts every file above
~1.9 GiB into parts (.001, .002, ...), GitHub accepts any number of such files, and the app joins them again. Users who
already have the app download only the changed files (differential update), not the whole gpu package.

How it works
    1. Finds the builds: the --dist folders, or else dist/<base|cpu|gpu>/DiplomaChecker (what build_linux.sh /
       build_windows.ps1 produce). The platform comes from the executable (DiplomaChecker.exe = windows).
    2. Runs prepare_release_assets for each build. It stops if a build is not of the version in --tag.
    3. Creates the release as a DRAFT if it does not exist yet. Running apps ignore drafts, so nobody gets a
       half-uploaded release. Run the script on Linux and on Windows with the same tag: both upload to the same draft.
    4. Uploads the files, retrying on network errors. Files already on the release with the same SHA-256 are skipped,
       so after an interrupted upload simply run the same command again. Old files of the same platform/variant that
       are no longer produced (e.g. a .003 part from an earlier, bigger build) are removed from the release.
    5. With --publish the draft becomes the public "latest" release; apps offer the update on their next start.
       Publish only after every platform/variant you want in this release has been uploaded.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import prepare_release_assets as prepare  # noqa: E402
from common.update_check import GITHUB_REPO  # noqa: E402

VARIANTS = ("base", "cpu", "gpu")
RETRIES = 4


def gh(*args, capture=True):
    result = subprocess.run(["gh", *args], capture_output=capture, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}... failed: {(result.stderr or '').strip()}")
    return result.stdout


def find_builds(extra):
    """[(folder, platform, variant)] of the --dist folders, or of the builds in dist/ when none is given."""
    folders = [(Path(d).resolve(), None) for d in extra]
    if not folders:
        folders = [(ROOT / "dist" / v / prepare.APP_DIR_NAME, v) for v in VARIANTS]
    builds = []
    for folder, variant in folders:
        if not (folder / "_internal").is_dir():
            if variant is None:
                sys.exit(f"{folder} is not a build folder (no _internal/)")
            continue
        if (folder / (prepare.APP_DIR_NAME + ".exe")).is_file():
            platform = "windows"
        elif (folder / prepare.APP_DIR_NAME).is_file():
            platform = "linux"
        else:
            sys.exit(f"{folder}: no {prepare.APP_DIR_NAME} executable inside")
        if variant is None:      # dist\gpu\DiplomaChecker -> gpu
            variant = folder.parent.name if folder.parent.name in VARIANTS else None
            if variant is None:
                sys.exit(f"{folder}: cannot tell the variant, the folder must lie in a base/cpu/gpu folder")
        builds.append((folder, platform, variant))
    return builds


def find_release(repo, tag):
    """The release (also a draft) with this tag, or None. /releases/tags/<tag> does not return drafts."""
    page = 1
    while True:
        releases = json.loads(gh("api", f"repos/{repo}/releases?per_page=100&page={page}"))
        for release in releases:
            if release["tag_name"] == tag:
                return release
        if len(releases) < 100:
            return None
        page += 1


def ensure_release(repo, tag):
    """The release with this tag; created as a draft when it does not exist yet."""
    release = find_release(repo, tag)
    if release is None:
        print(f"\nCreating draft release {tag} in {repo}")
        gh("release", "create", tag, "-R", repo, "--draft", "--title", tag, "--notes", f"DiplomaChecker {tag.lstrip('vV')}")
        release = find_release(repo, tag)
    elif not release["draft"]:
        print(f"\nNOTE: release {tag} is already public; files are replaced while users may be downloading")
    return release


def sha256_of(path):
    return "sha256:" + prepare.sha256_of(path)


def upload(repo, tag, path):
    for attempt in range(1, RETRIES + 1):
        try:
            gh("release", "upload", tag, str(path), "--clobber", "-R", repo, capture=False)
            return
        except RuntimeError as e:
            if attempt == RETRIES:
                raise
            wait = 15 * attempt
            print(f"  upload of {path.name} failed ({e}), retrying in {wait} s")
            time.sleep(wait)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="release tag, e.g. v0.3.1 (must match APP_VERSION of the builds)")
    ap.add_argument("--dist", action="append", default=[], help="another build folder (repeatable)")
    ap.add_argument("--repo", default=GITHUB_REPO, help=f"download repository (default {GITHUB_REPO})")
    ap.add_argument("--out", type=Path, default=ROOT / "release_files", help="where the packed files are written")
    ap.add_argument("--only", choices=VARIANTS, action="append", help="upload only these variants (repeatable)")
    ap.add_argument("--publish", action="store_true", help="make the release public and latest at the end")
    ap.add_argument("--no-upload", action="store_true", help="only pack, do not touch GitHub")
    args = ap.parse_args(argv)


    builds = [b for b in find_builds(args.dist) if not args.only or b[2] in args.only]
    if not builds and not args.publish:
        sys.exit("No builds found in dist/ - build first or pass --dist")
    out = args.out / args.tag

    produced = {}
    for folder, platform, variant in builds:
        print(f"\n=== {platform}-{variant}: {folder}")
        produced[(platform, variant)] = prepare.main([str(folder), "--platform", platform, "--variant", variant,
                                                      "--tag", args.tag, "--out", str(out)])
    if args.no_upload:
        return

    release = ensure_release(args.repo, args.tag)
    online = {a["name"]: a for a in release.get("assets", [])}

    for (platform, variant), files in produced.items():
        prefix = f"{prepare.APP_DIR_NAME}-{platform}-{variant}."
        names = {f.name for f in files}
        for name in sorted(n for n in online if n.startswith(prefix) and n not in names):
            print(f"  removing old {name}")
            gh("release", "delete-asset", args.tag, name, "-R", args.repo, "--yes")
        for path in files:
            have = online.get(path.name)
            if have and have.get("digest") == sha256_of(path):
                print(f"  {path.name}: already uploaded")
                continue
            print(f"  uploading {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MiB)")
            upload(args.repo, args.tag, path)

    if args.publish:
        gh("release", "edit", args.tag, "-R", args.repo, "--draft=false", "--latest")
        print(f"\nRelease {args.tag} is public. Running apps will offer the update on their next start.")
    else:
        print(f"\nUploaded to the draft {args.tag}. When every platform is there, run again with --publish "
              f"(or publish it on https://github.com/{args.repo}/releases).")


if __name__ == "__main__":
    main()

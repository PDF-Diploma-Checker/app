"""Prepare the files of a release for the in-app updater.

Usage (after building a variant with the build scripts):

    python tools/prepare_release_assets.py <dist-folder> --platform windows --variant gpu
    python tools/prepare_release_assets.py dist/DiplomaChecker --platform linux --variant cpu --out release_files

<dist-folder> is the PyInstaller output folder (contains DiplomaChecker(.exe) and _internal/).

What it does
    1. Packs the folder into  DiplomaChecker-<platform>-<variant>.zip  (windows) or  .tar.gz  (linux). Models, logs and
       data are never packed, even if they happen to lie next to the build.
    2. Writes  <archive>.sha256  with the SHA-256 of the whole archive (the app checks it after downloading).
    3. A GitHub release file may be at most 2 GiB. A bigger archive is cut into  <archive>.001, .002, ...  (the app
       joins them again); the checksum file still describes the whole archive.
    4. Builds the data for DIFFERENTIAL updates (skip with --no-delta):
         DiplomaChecker-<platform>-<variant>.manifest.json   every file with its SHA-256 and place in the pack
         DiplomaChecker-<platform>-<variant>.pack.001, ...   the files, compressed one by one, in parts below 2 GiB
       With these an installed app downloads only the files that changed (usually a few MB, not GBs), whatever older
       version it comes from. The full archive stays for first installs and as the fallback. The release therefore
       holds each variant twice (archive + pack): that is fine for GitHub (only 2 GiB per file counts).
    5. Prints the list of files to upload to the release.

Release procedure
    1. Put the new number in  src/common/version.py  (APP_VERSION) - it must be equal to the release tag without "v".
    2. Build each variant, run this script for each one.
    3. Create a GitHub release with that tag in the download repository and upload every file the script printed.
    4. Running apps find the release on start and offer "Update now". Nothing is installed again; models stay.
    Upload ALL printed files of a variant together. A release may hold several platforms/variants.
"""

import argparse
import hashlib
import re
import sys
import tarfile
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from common import delta  # noqa: E402  (the same code the app uses to read the manifest)

APP_DIR_NAME = "DiplomaChecker"
EXCLUDE = set(delta.PRESERVE)
PART_SIZE = 1900 * 1024 * 1024          # a little under GitHub's 2 GiB limit per file
CHUNK = 8 * 1024 * 1024


def _files(root):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] in EXCLUDE or path.is_dir():
            continue
        yield path, rel


def pack_zip(root, target):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for path, rel in _files(root):
            z.write(path, (Path(APP_DIR_NAME) / rel).as_posix())


def pack_tar(root, target):
    with tarfile.open(target, "w:gz", compresslevel=6) as t:
        for path, rel in _files(root):
            t.add(path, (Path(APP_DIR_NAME) / rel).as_posix(), recursive=False)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def split_file(path, part_size=PART_SIZE):
    """Cut `path` into path.001, path.002, ... and remove the original. Returns the list of parts."""
    parts = []
    with open(path, "rb") as src:
        index = 1
        while True:
            chunk = src.read(min(CHUNK, part_size))
            if not chunk:
                break
            part = path.with_name(f"{path.name}.{index:03d}")
            written = 0
            with open(part, "wb") as out:
                while chunk:
                    out.write(chunk)
                    written += len(chunk)
                    if written >= part_size:
                        break
                    chunk = src.read(min(CHUNK, part_size - written))
            parts.append(part)
            index += 1
    path.unlink()
    return parts


def _app_version():
    match = re.search(r"APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", (SRC / "common" / "version.py").read_text(encoding="utf-8"))
    if not match:
        sys.exit("APP_VERSION not found in src/common/version.py: pass --version")
    return match.group(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dist", type=Path, help="PyInstaller output folder (with the executable and _internal/)")
    ap.add_argument("--platform", choices=("windows", "linux"), required=True)
    ap.add_argument("--variant", choices=("base", "cpu", "gpu"), required=True)
    ap.add_argument("--out", type=Path, default=Path("release_files"))
    ap.add_argument("--part-size-mib", type=int, default=PART_SIZE // (1024 * 1024))
    ap.add_argument("--version", help="release version (default: APP_VERSION from src/common/version.py)")
    ap.add_argument("--no-delta", action="store_true", help="do not build the manifest and pack for differential updates")
    args = ap.parse_args(argv)

    exe = APP_DIR_NAME + (".exe" if args.platform == "windows" else "")
    if not (args.dist / exe).is_file() or not (args.dist / "_internal").is_dir():
        sys.exit(f"{args.dist} does not look like the build output: {exe} and _internal/ are expected there")

    args.out.mkdir(parents=True, exist_ok=True)
    name = f"{APP_DIR_NAME}-{args.platform}-{args.variant}." + ("zip" if args.platform == "windows" else "tar.gz")
    archive = args.out / name
    print(f"Packing {args.dist} -> {archive}")
    (pack_zip if args.platform == "windows" else pack_tar)(args.dist, archive)

    digest = sha256_of(archive)
    sidecar = args.out / (name + ".sha256")
    sidecar.write_text(f"{digest}  {name}\n", encoding="utf-8")

    part_size = args.part_size_mib * 1024 * 1024
    uploads = [sidecar]
    if archive.stat().st_size > part_size:
        uploads = split_file(archive, part_size) + uploads
    else:
        uploads = [archive] + uploads

    if not args.no_delta:
        version = args.version or _app_version()
        print(f"Building the differential update data for version {version}")
        manifest = delta.build_pack(args.dist, args.out, args.platform, args.variant, version, part_size=part_size)
        uploads += [args.out / part["name"] for part in manifest["parts"]]
        uploads.append(args.out / delta.manifest_name(args.platform, args.variant))

    print("\nUpload these files to the GitHub release:")
    for path in uploads:
        print(f"  {path.name:55s} {path.stat().st_size / 1024 / 1024:9.1f} MiB")
    print(f"\nSHA-256 of the whole archive: {digest}")


if __name__ == "__main__":
    main()
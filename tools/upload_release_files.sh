#!/usr/bin/env bash
# Puts the release files of one variant (the output of tools/prepare_release_assets.py) into the DRAFT of a release in
# the download repository. The draft is created when it does not exist. Files of the same platform and variant that
# are already there are replaced (also leftovers such as a .003 part of an earlier, bigger build). It never publishes:
# publish the draft yourself when every platform and variant is in it.
# Usage: tools/upload_release_files.sh <tag> <platform> <variant> <folder-with-the-files>
# Needs the GitHub CLI with a token that can write to the download repository (GH_TOKEN).
set -euo pipefail
TAG="${1:?tag}"; PLATFORM="${2:?platform}"; VARIANT="${3:?variant}"; DIR="${4:?folder}"
REPO="${DOWNLOAD_REPO:-PDF-Diploma-Checker/diploma-checker-download}"
PREFIX="DiplomaChecker-$PLATFORM-$VARIANT."

if ! gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  # the Windows and Linux workflows may create it at the same moment: the one that loses finds it afterwards
  gh release create "$TAG" -R "$REPO" --draft --title "$TAG" --notes "DiplomaChecker ${TAG#v}" \
    || gh release view "$TAG" -R "$REPO" >/dev/null
fi
if [ "$(gh release view "$TAG" -R "$REPO" --json isDraft --jq .isDraft)" != "true" ]; then
  echo "Release $TAG is already published: refusing to change it."; exit 1
fi

gh release view "$TAG" -R "$REPO" --json assets --jq '.assets[].name' | grep -F "$PREFIX" | while read -r name; do
  gh release delete-asset "$TAG" "$name" -R "$REPO" --yes
done || true

shopt -s nullglob
files=("$DIR"/*)
[ ${#files[@]} -gt 0 ] || { echo "No files in $DIR"; exit 1; }
for f in "${files[@]}"; do
  echo "uploading $(basename "$f")"
  for attempt in 1 2 3 4; do
    gh release upload "$TAG" "$f" -R "$REPO" --clobber && break
    [ "$attempt" = 4 ] && exit 1
    sleep $((attempt * 20))
  done
done
echo "Uploaded $PLATFORM-$VARIANT to the draft $TAG"

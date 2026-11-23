#!/usr/bin/env bash
# Runs inside the image of docker/linux-build.Dockerfile with the repository mounted at /src.
# Usage: build_in_container.sh base|cpu|gpu [release-tag]      -> release files in /src/release_files
set -euo pipefail
VARIANT="${1:?usage: build_in_container.sh base|cpu|gpu [release-tag]}"
TAG="${2:-}"
cd /src

SCRIPT=./build_linux.sh
if [ "$VARIANT" = "gpu" ]; then
  # build_linux.sh refuses a gpu build whose llama.cpp "cannot offload to a GPU", but a build machine has no GPU and
  # the answer is then always "no". Use a copy that skips that one check when there is no nvidia-smi; the check of
  # the CUDA architectures below (and the smoke test) still fail a build without working CUDA code.
  SCRIPT=./.build_linux_ci.sh
  python3 - <<'PY'
from pathlib import Path
src = Path("build_linux.sh").read_text(encoding="utf-8")
old = "sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)"
new = "import shutil; sys.exit(0 if (llama_cpp.llama_supports_gpu_offload() or not shutil.which('nvidia-smi')) else 1)"
assert old in src, "build_linux.sh changed: update docker/build_in_container.sh"
Path(".build_linux_ci.sh").write_text(src.replace(old, new), encoding="utf-8")
PY
  chmod +x "$SCRIPT"
  trap 'rm -f .build_linux_ci.sh' EXIT
fi

"$SCRIPT" "$VARIANT"

PY=".venv-build-$VARIANT/bin/python"
if [ "$VARIANT" = "gpu" ]; then
  LIB="$("$PY" -c 'import llama_cpp, os; print(os.path.join(os.path.dirname(llama_cpp.__file__), "lib"))')"
  "$PY" tools/check_cuda_archs.py "$LIB/libggml-cuda.so"
fi

rm -f "DiplomaChecker-linux-$VARIANT.tar.gz"      # prepare_release_assets packs the build itself
rm -rf release_files
TAG_ARGS=()
[ -n "$TAG" ] && TAG_ARGS=(--tag "$TAG")
"$PY" tools/prepare_release_assets.py "dist/$VARIANT/DiplomaChecker" --platform linux --variant "$VARIANT" \
  --out release_files ${TAG_ARGS[@]+"${TAG_ARGS[@]}"}

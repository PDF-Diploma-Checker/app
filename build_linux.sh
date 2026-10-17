#!/usr/bin/env bash
# Usage: ./build_linux.sh [base|cpu|gpu|all]
#   base - no AI libraries (rule-based analysis only)
#   cpu  - base + torch (CPU wheels), llama-cpp-python, sentence-transformers
#   gpu  - same as cpu, but torch with CUDA and llama-cpp-python built with CUDA
#          (needs the CUDA Toolkit: `nvcc` must be on PATH; the archive is several GB)
#   all  - base, cpu and gpu, one after another
#
# Use a ready environment instead of building a new one (no uv sync, nothing is compiled):
#   PYTHON_BIN=/path/to/.venv/bin/python ./build_linux.sh gpu
# The environment must already match the variant (e.g. torch with CUDA and a CUDA build of
# llama-cpp-python for gpu). Works with a single variant only, not with "all".
#
# Every variant gets its own environment (.venv-build-<variant>) and its own output folder
# (dist/<variant>), so the variants never mix and your development .venv is left alone.
set -euo pipefail
cd "$(dirname "$0")"

VARIANT="${1:-base}"
case "$VARIANT" in
  base|cpu|gpu|all) ;;
  *) echo "Usage: ./build_linux.sh [base|cpu|gpu|all]"; exit 1 ;;
esac

HAVE_UV=0
if command -v uv >/dev/null 2>&1 && [ -f uv.lock ]; then
  HAVE_UV=1
fi
if [ "$VARIANT" = "all" ] && [ "$HAVE_UV" = "0" ]; then
  echo "'all' needs uv and uv.lock (one environment per variant). Build the variants separately instead."
  exit 1
fi
if [ -n "${PYTHON_BIN:-}" ]; then
  if [ "$VARIANT" = "all" ]; then
    echo "PYTHON_BIN dziala tylko z jednym wariantem (base, cpu albo gpu), nie z 'all'."
    exit 1
  fi
  if [ ! -x "$PYTHON_BIN" ]; then
    echo "PYTHON_BIN nie wskazuje na wykonywalny plik: $PYTHON_BIN"
    exit 1
  fi
elif { [ "$VARIANT" = "gpu" ] || [ "$VARIANT" = "all" ]; } && ! command -v nvcc >/dev/null 2>&1; then
  echo "Wariant gpu wymaga CUDA Toolkit (brak 'nvcc' w PATH): llama-cpp-python jest kompilowany z CUDA."
  echo "Zainstaluj toolkit albo zbuduj tylko base/cpu."
  exit 1
fi

build_one() {
  local variant="$1"
  local extra=()
  local build_env=()
  case "$variant" in
    cpu) extra=(--extra cpu) ;;
    gpu) extra=(--extra gpu); build_env=(CMAKE_ARGS=-DGGML_CUDA=on) ;;
  esac

  echo
  echo "=== Wariant: $variant ==="

  local py
  if [ -n "${PYTHON_BIN:-}" ]; then
    py="$PYTHON_BIN"
    echo "Uzywam gotowego srodowiska: $py (bez uv sync, nic nie jest kompilowane)"
    echo "Musi odpowiadac wariantowi '$variant'; sprawdzenie dla gpu ponizej."
    if command -v uv >/dev/null 2>&1; then
      uv pip install --python "$py" pyinstaller
    else
      "$py" -m pip install pyinstaller
    fi
  elif [ "$HAVE_UV" = "1" ]; then
    local venv=".venv-build-$variant"
    unset VIRTUAL_ENV            # an activated dev venv must not leak into the build
    export UV_PROJECT_ENVIRONMENT="$venv"
    # llama-cpp-python is compiled from source and uv's wheel cache does not know about CMAKE_ARGS:
    # drop a cached build, otherwise a CUDA-less wheel could be reused for gpu (or the other way round).
    if [ ! -d "$venv" ] && { [ "$variant" = "cpu" ] || [ "$variant" = "gpu" ]; }; then
      uv cache clean llama-cpp-python || true
    fi
    # "uv sync" is exact: packages that are not part of this variant (e.g. CUDA torch) are removed.
    env ${build_env[@]+"${build_env[@]}"} uv sync --frozen --no-dev ${extra[@]+"${extra[@]}"}
    uv pip install --python "$venv/bin/python" pyinstaller
    py="$venv/bin/python"
  else
    # No uv: builds with whatever is installed in the current Python environment.
    python -m pip install pyinstaller
    py="python"
  fi

  if [ "$variant" = "gpu" ]; then
    "$py" -c "import sys, llama_cpp; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" || {
      echo "llama-cpp-python w tym srodowisku jest zbudowany BEZ CUDA."
      echo "Usun .venv-build-gpu, wykonaj 'uv cache clean llama-cpp-python' i uruchom ponownie."
      exit 1
    }
  fi

  if [ "$variant" = "gpu" ] && [ -n "${PYTHON_BIN:-}" ]; then
    "$py" -c "import sys, torch; sys.exit(0 if torch.version.cuda else 1)" || {
      echo "torch w tym srodowisku jest bez CUDA (wariant gpu wymaga wersji z CUDA)."
      exit 1
    }
  fi

  "$py" tools/check_imports.py
  "$py" -m PyInstaller --noconfirm --distpath "dist/$variant" --workpath "build/$variant" DiplomaChecker.spec

  rm -f smoke_test.log
  QT_QPA_PLATFORM=offscreen "./dist/$variant/DiplomaChecker/DiplomaChecker" --smoke-test || { cat smoke_test.log 2>/dev/null || true; exit 1; }
  cat smoke_test.log 2>/dev/null || true
  echo

  local archive="DiplomaChecker-linux-$variant.tar.gz"
  tar -czf "$archive" -C "dist/$variant" DiplomaChecker
  echo "Gotowe: $archive ($(du -h "$archive" | cut -f1), folder: $(du -sh "dist/$variant/DiplomaChecker" | cut -f1))"
}

if [ "$VARIANT" = "all" ]; then
  build_one base
  build_one cpu
  build_one gpu
else
  build_one "$VARIANT"
fi
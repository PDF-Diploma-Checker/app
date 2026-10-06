#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

case "${1:-}" in
    "")  uv sync ;;
    cpu) uv sync --extra cpu --reinstall-package llama-cpp-python ;;
    gpu) CMAKE_ARGS="-DGGML_CUDA=on" uv sync --extra gpu --reinstall-package llama-cpp-python ;;
    *)   echo "Usage: ./setup.sh [cpu|gpu]"; exit 1 ;;
esac

LTP_PATH="$HOME/DiplomaChecker/LanguageTool" uv run python -c "from language_tool_python.download_lt import download_lt; download_lt('6.6')"

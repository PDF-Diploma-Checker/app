#!/usr/bin/env bash
# Usage: ./build_linux.sh [base|cpu]
set -euo pipefail
cd "$(dirname "$0")"
VARIANT="${1:-base}"

if command -v uv >/dev/null 2>&1 && [ -f uv.lock ] && [ -z "${VIRTUAL_ENV:-}" ]; then
  EXTRA=""
  [ "$VARIANT" = "cpu" ] && EXTRA="--extra cpu"
  uv sync --frozen --no-dev $EXTRA
  uv pip install pyinstaller
  RUN="uv run --no-sync"
else
  python -m pip install pyinstaller
  RUN=""
fi

$RUN python tools/check_imports.py
$RUN python -m PyInstaller --noconfirm DiplomaChecker.spec

QT_QPA_PLATFORM=offscreen ./dist/DiplomaChecker/DiplomaChecker --smoke-test || { cat smoke_test.log; exit 1; }
cat smoke_test.log; echo

tar -czf "DiplomaChecker-linux-$VARIANT.tar.gz" -C dist DiplomaChecker
echo "Gotowe: DiplomaChecker-linux-$VARIANT.tar.gz"
#!/usr/bin/env bash
# Start the TCF B2 trainer. Run from the project root or from demo/.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

# The venv Python is a universal binary. On Apple Silicon, a Rosetta/x86_64 terminal
# launches it as x86_64, which can't load the arm64 psycopg wheel. Pin to arm64 so the
# interpreter and the installed wheels match. Note: under Rosetta `uname -m` lies and
# says x86_64, so we test whether arm64 can actually run instead.
RUN="$PY"
if arch -arm64 true >/dev/null 2>&1; then
  RUN="arch -arm64 $PY"
fi

$RUN -m pip install -q -r demo/requirements.txt
$RUN -m demo.app.seed
echo "→ http://127.0.0.1:8000"
$RUN -m uvicorn demo.app.main:app --reload --port 8000

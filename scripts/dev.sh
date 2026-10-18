#!/usr/bin/env bash
# Arranca la API y el frontend con el venv del proyecto en http://127.0.0.1:8765.
# Para otro puerto: PORT=8766 scripts/dev.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
FULL_FFMPEG=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg

if [ ! -x .venv/bin/python ]; then
  echo "No existe .venv. Créalo con:" >&2
  echo "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r backend/requirements.txt" >&2
  exit 1
fi

if [ "$(uname -s)" = "Darwin" ] && [ ! -x "$FULL_FFMPEG" ]; then
  echo "Aviso: no encuentro ffmpeg-full en /opt/homebrew/opt/ffmpeg-full/bin/." >&2
  echo "  La API arranca, pero sin libass no se puede quemar el video." >&2
  echo "  Instálalo con: brew install ffmpeg-full" >&2
fi

exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "$PORT"

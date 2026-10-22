#!/usr/bin/env bash
# Arranca el backend para launchd (com.clickflow.subs). La clave de acceso sale de .secrets.env, así que no queda
# escrita en el plist. El backend corre en segundo plano y su pid queda en state/backend.pid. caffeinate -s solo impide
# que el Mac se duerma con corriente mientras ese pid vive. Al parar este script (launchd o SIGTERM) para también el backend.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SUBS_API_KEY="$(read_secret SUBS_API_KEY)"
[ -n "$SUBS_API_KEY" ] || die "falta SUBS_API_KEY en $SECRETS_FILE (ejecuta deploy.sh una vez)"
export SUBS_API_KEY
export SUBS_MAX_UPLOAD_MB="$MAX_UPLOAD_MB"
export SUBS_DATA_DIR="$DATA_DIR"
# Sitio público (Worker): el banner de la versión local consulta /api/local-ping desde su navegador. Sale de state/public_url.
PUBLIC_URL="$(cat "$STATE_DIR/public_url" 2>/dev/null || true)"
if [ -n "$PUBLIC_URL" ]; then export SUBS_PUBLIC_ORIGINS="$PUBLIC_URL"; fi
mkdir -p "$DATA_DIR" "$LOG_DIR" "$STATE_DIR"
cd "$ROOT"
"$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" > "$STATE_DIR/backend.pid"
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; wait "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup TERM INT
/usr/bin/caffeinate -s -w "$BACKEND_PID" &
wait "$BACKEND_PID" 2>/dev/null || true

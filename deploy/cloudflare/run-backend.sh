#!/usr/bin/env bash
# Arranca el backend para launchd (com.clickflow.subs). La clave de acceso sale de .secrets.env, así que no queda
# escrita en el plist. caffeinate -i evita que el Mac se duerma mientras corre.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SUBS_API_KEY="$(read_secret SUBS_API_KEY)"
[ -n "$SUBS_API_KEY" ] || die "falta SUBS_API_KEY en $SECRETS_FILE (ejecuta deploy.sh una vez)"
export SUBS_API_KEY
export SUBS_MAX_UPLOAD_MB="$MAX_UPLOAD_MB"
mkdir -p "$LOG_DIR" "$STATE_DIR"
cd "$ROOT"
# El backend corre en segundo plano y su pid queda en state/backend.pid: es el que hay que parar para reiniciarlo.
# caffeinate -i solo impide que el Mac se duerma mientras ese pid vive. Al parar este script, para también el backend.
"$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" > "$STATE_DIR/backend.pid"
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; wait "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup TERM INT
/usr/bin/caffeinate -i -w "$BACKEND_PID" &
wait "$BACKEND_PID" 2>/dev/null || true

#!/usr/bin/env bash
# Arranca el backend para launchd (com.clickflow.subs). La clave de acceso sale de .secrets.env, así que no queda
# escrita en el plist. caffeinate -i evita que el Mac se duerma mientras corre.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SUBS_API_KEY="$(read_secret SUBS_API_KEY)"
[ -n "$SUBS_API_KEY" ] || die "falta SUBS_API_KEY en $SECRETS_FILE (ejecuta deploy.sh una vez)"
export SUBS_API_KEY
export SUBS_MAX_UPLOAD_MB="$MAX_UPLOAD_MB"
mkdir -p "$LOG_DIR"
cd "$ROOT"
exec /usr/bin/caffeinate -i "$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT"

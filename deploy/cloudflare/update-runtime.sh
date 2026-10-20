#!/usr/bin/env bash
# Pone el runtime de launchd al día con GitHub: git pull (solo avance rápido), pip solo si cambiaron los requisitos,
# reinicia los dos agentes y comprueba que el backend y el sitio responden. Uso: update-runtime.sh (desde cualquier sitio).
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

case "$ROOT" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    die "este clon está en $ROOT: launchd no puede leerlo. Usa el runtime de ~/Services." ;;
esac
[ -z "$(git -C "$ROOT" status --porcelain)" ] || die "el runtime tiene cambios sin commit; revísalos antes de actualizar"

antes="$(git -C "$ROOT" rev-parse HEAD)"
git -C "$ROOT" pull --ff-only origin main
despues="$(git -C "$ROOT" rev-parse HEAD)"
if [ "$antes" = "$despues" ]; then
  log "ya estaba al día en ${despues:0:7}"
else
  log "actualizado de ${antes:0:7} a ${despues:0:7}"
  if ! git -C "$ROOT" diff --quiet "$antes" "$despues" -- requirements.txt backend/requirements.txt; then
    log "cambiaron los requisitos: instalo"
    "$PY" -m pip install -q -r "$ROOT/requirements.txt" -r "$ROOT/backend/requirements.txt"
  fi
fi

for label in com.clickflow.subs com.clickflow.subs-tunnel; do
  launchctl kickstart -k "gui/$(id -u)/$label"
  log "reiniciado $label"
done

# Reintenta cada 2 s durante 90 s hasta que el comando acierta.
esperar() {
  local descripcion="$1" i
  shift
  for i in $(seq 1 45); do
    if "$@" > /dev/null 2>&1; then log "$descripcion: responde"; return 0; fi
    sleep 2
  done
  log "$descripcion: sin respuesta tras 90 s"
  return 1
}

key="$(read_secret SUBS_API_KEY)"
esperar "backend local" curl -sf -m 5 -H "X-Subs-Key: $key" "http://127.0.0.1:$BACKEND_PORT/api/config"
publica="$(cat "$STATE_DIR/public_url" 2>/dev/null || true)"
if [ -n "$publica" ]; then esperar "sitio público" curl -sf -m 10 -o /dev/null "$publica/login"; fi

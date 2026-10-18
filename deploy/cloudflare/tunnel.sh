#!/usr/bin/env bash
# Túnel rápido de Cloudflare hacia el backend (127.0.0.1:8765), sin cuenta ni dominio. Si la URL no está ya
# desplegada, guarda BACKEND_URL y lo actualiza en el Worker. Si cloudflared muere, lo reinicia. Lo ejecuta launchd
# (com.clickflow.subs-tunnel). SIGTERM lo para y para también cloudflared.
set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
mkdir -p "$STATE_DIR" "$LOG_DIR"
CHILD=""

stop() {
  log "parando el túnel"
  if [ -n "$CHILD" ]; then kill "$CHILD" 2>/dev/null || true; fi
  exit 0
}
trap stop TERM INT

while true; do
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$BACKEND_PORT" > "$LOG_DIR/cloudflared.log" 2>&1 &
  CHILD=$!
  log "cloudflared arrancado (pid $CHILD)"
  url=""
  for _ in $(seq 1 90); do
    url="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" | head -n 1 || true)"
    [ -n "$url" ] && break
    kill -0 "$CHILD" 2>/dev/null || break
    sleep 1
  done
  if [ -z "$url" ]; then
    log "cloudflared no anunció URL en 90 s"
  else
    printf '%s\n' "$url" > "$STATE_DIR/tunnel_url"
    if [ "$url" != "$(cat "$STATE_DIR/deployed_url" 2>/dev/null || true)" ]; then
      log "URL del túnel: $url. Actualizo BACKEND_URL en el Worker."
      write_secret BACKEND_URL "$url"
      # En subshell: si wrangler falla, put_secret termina solo esa subshell y el bucle sigue vivo.
      if ( put_secret BACKEND_URL "$url" ); then
        printf '%s\n' "$url" > "$STATE_DIR/deployed_url"
        log "el Worker ya apunta al túnel nuevo."
      else
        log "no se pudo actualizar BACKEND_URL; se reintenta cuando cambie la URL"
      fi
    else
      log "túnel activo en $url, ya en el Worker"
    fi
  fi
  wait "$CHILD"
  CHILD=""
  log "cloudflared terminó; reinicio en 5 s"
  sleep 5
done

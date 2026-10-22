#!/usr/bin/env bash
# Túnel rápido de Cloudflare hacia el backend (127.0.0.1:8765), sin cuenta ni dominio. Si cloudflared muere, lo reinicia.
# Cada URL nueva se fija como BACKEND_URL en el Worker, con reintentos y espera creciente (hasta 60 s) si la red falla.
# Un vigilante comprueba cada 60 s el backend en local, el túnel y el camino completo Worker → túnel. Con 3 fallos
# seguidos reinicia cloudflared (si el backend está sano) o vuelve a fijar BACKEND_URL (si el túnel sí responde).
# Lo ejecuta launchd (com.clickflow.subs-tunnel). SIGTERM lo para y para también cloudflared y el vigilante.
set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
mkdir -p "$STATE_DIR" "$LOG_DIR"
CHILD=""
VIGILANTE=""

stop() {
  log "parando el túnel"
  if [ -n "$VIGILANTE" ]; then kill "$VIGILANTE" 2>/dev/null || true; fi
  if [ -n "$CHILD" ]; then kill "$CHILD" 2>/dev/null || true; fi
  exit 0
}
trap stop TERM INT

# Fija BACKEND_URL en el Worker. Si wrangler falla (p. ej. sin red), espera 5, 10, 20… hasta 60 s entre intentos.
# Devuelve 0 cuando lo consigue. Lo usan el bucle principal y el vigilante.
fijar_backend() {
  local url="$1" espera=5 intento
  for intento in 1 2 3 4 5 6 7 8; do
    # En subshell: si wrangler falla, put_secret termina solo esa subshell.
    if ( put_secret BACKEND_URL "$url" ); then
      printf '%s\n' "$url" > "$STATE_DIR/deployed_url"
      log "el Worker apunta al túnel: $url (intento $intento)"
      return 0
    fi
    log "no se pudo fijar BACKEND_URL (intento $intento); reintento en ${espera} s"
    sleep "$espera"
    espera=$(( espera * 2 > 60 ? 60 : espera * 2 ))
  done
  return 1
}

# Código HTTP de una petición (000 si no hay conexión).
codigo() { curl -s -m 20 -o /dev/null -w '%{http_code}' "$@"; }

# Camino completo: entra con la contraseña del sitio y pide /api/config a través del Worker. 0 si responde 200.
worker_ok() {
  local publica="$1" pw jar code
  pw="$(read_secret SITE_PASSWORD)"
  jar="$(mktemp)"
  printf 'password=%s&next=/' "$pw" | curl -s -m 20 -c "$jar" -o /dev/null --data-binary @- "$publica/login" || true
  code="$(curl -s -m 20 -b "$jar" -o /dev/null -w '%{http_code}' "$publica/api/config")"
  rm -f "$jar"
  [ "$code" = 200 ]
}

# Vigilante: cada 60 s comprueba el backend en local, el túnel y el camino Worker → túnel. Ver la cabecera.
vigilante() {
  local key url publica local_code tunel_code fallos_tunel=0 fallos_worker=0
  sleep 90
  while true; do
    key="$(read_secret SUBS_API_KEY)"
    url="$(cat "$STATE_DIR/tunnel_url" 2>/dev/null || true)"
    publica="$(cat "$STATE_DIR/public_url" 2>/dev/null || true)"
    local_code="$(codigo -H "X-Subs-Key: $key" "http://127.0.0.1:$BACKEND_PORT/api/config")"
    if [ "$local_code" != 200 ]; then
      fallos_tunel=0
      fallos_worker=0
      log "vigilante: backend local sin respuesta ($local_code); lo vigila launchd"
    elif [ -n "$url" ]; then
      tunel_code="$(codigo -H "X-Subs-Key: $key" "$url/api/config")"
      if [ "$tunel_code" != 200 ]; then
        fallos_worker=0
        fallos_tunel=$((fallos_tunel + 1))
        log "vigilante: túnel sin respuesta ($tunel_code), fallo $fallos_tunel de 3"
        if [ "$fallos_tunel" -ge 3 ]; then
          fallos_tunel=0
          log "vigilante: 3 fallos seguidos del túnel con el backend sano: reinicio cloudflared"
          kill "$(cat "$STATE_DIR/cloudflared.pid" 2>/dev/null)" 2>/dev/null || true
        fi
      else
        fallos_tunel=0
        if [ -n "$publica" ] && ! worker_ok "$publica"; then
          fallos_worker=$((fallos_worker + 1))
          log "vigilante: el Worker no llega al túnel, fallo $fallos_worker de 3"
          if [ "$fallos_worker" -ge 3 ]; then
            fallos_worker=0
            log "vigilante: BACKEND_URL no apunta al túnel: lo vuelvo a fijar"
            fijar_backend "$url" || log "vigilante: sigo sin poder fijar BACKEND_URL; reintento en el siguiente ciclo"
          fi
        else
          fallos_worker=0
        fi
      fi
    fi
    sleep 60
  done
}

vigilante &
VIGILANTE=$!

while true; do
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$BACKEND_PORT" > "$LOG_DIR/cloudflared.log" 2>&1 &
  CHILD=$!
  printf '%s\n' "$CHILD" > "$STATE_DIR/cloudflared.pid"
  log "cloudflared arrancado (pid $CHILD)"
  url=""
  for _ in $(seq 1 90); do
    url="$(grep -aEo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" | head -n 1 || true)"
    [ -n "$url" ] && break
    kill -0 "$CHILD" 2>/dev/null || break
    sleep 1
  done
  if [ -z "$url" ]; then
    log "cloudflared no anunció URL en 90 s"
  else
    printf '%s\n' "$url" > "$STATE_DIR/tunnel_url"
    if [ "$url" != "$(cat "$STATE_DIR/deployed_url" 2>/dev/null || true)" ]; then
      log "URL del túnel nueva: $url"
      write_secret BACKEND_URL "$url"
      fijar_backend "$url" || log "BACKEND_URL sin fijar; el vigilante lo reintenta"
    else
      log "túnel activo en $url, ya en el Worker"
    fi
  fi
  wait "$CHILD"
  CHILD=""
  log "cloudflared terminó; reinicio en 5 s"
  sleep 5
done

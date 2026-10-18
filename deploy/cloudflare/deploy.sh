#!/usr/bin/env bash
# Publica el sitio como Worker con assets estáticos (worker.js y wrangler.jsonc). Genera el paquete, despliega y
# sube los secretos. Sin secretos el Worker falla cerrado: el despliegue inicial no deja pasar nada.
# La primera vez crea los secretos (la contraseña se muestra una sola vez). tunnel.sh actualiza BACKEND_URL
# cuando cambia la URL del túnel.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
mkdir -p "$STATE_DIR" "$LOG_DIR"

ensure_secrets
"$CF_DIR/build.sh"
deploy_site 2>&1 | tee "$LOG_DIR/wrangler-deploy.log"
put_secret SITE_PASSWORD "$(read_secret SITE_PASSWORD)"
put_secret SESSION_SECRET "$(read_secret SESSION_SECRET)"
put_secret SUBS_API_KEY "$(read_secret SUBS_API_KEY)"
backend="$(read_secret BACKEND_URL)"
if [ -n "$backend" ]; then
  put_secret BACKEND_URL "$backend"
  printf '%s\n' "$backend" > "$STATE_DIR/deployed_url"
else
  log "BACKEND_URL todavía no existe: el túnel la fijará al arrancar. Hasta entonces el proxy responde 503."
fi
public="$(grep -Eo 'https://[A-Za-z0-9.-]+\.workers\.dev' "$LOG_DIR/wrangler-deploy.log" | head -n 1 || true)"
if [ -n "$public" ]; then printf '%s\n' "$public" > "$STATE_DIR/public_url"; fi
log "sitio: ${public:-(URL no detectada; mira $LOG_DIR/wrangler-deploy.log)}"

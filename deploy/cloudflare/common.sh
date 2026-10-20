#!/usr/bin/env bash
# Piezas comunes de deploy/cloudflare: rutas, secretos locales y llamadas a wrangler. Se cargan con `. common.sh`
# y no ejecutan nada por sí mismas.

CF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CF_DIR/../.." && pwd)"
BUILD_DIR="$CF_DIR/build"
STATE_DIR="$CF_DIR/state"
SECRETS_FILE="$CF_DIR/.secrets.env"
DATA_DIR="${SUBS_DATA_DIR:-$ROOT/data}"  # datos del backend; en launchd apuntan fuera del repo
LOG_DIR="$DATA_DIR/logs"
PY="$ROOT/.venv/bin/python"
WORKER_NAME="${WORKER_NAME:-subtitulos}"
BACKEND_PORT=8765
MAX_UPLOAD_MB=500
export CLOUDFLARE_ACCOUNT_ID="191c2077c2aed814603696b1fea5a14b"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "error: $*" >&2; exit 1; }

# Valor de una clave de .secrets.env. Vacío si no existe.
read_secret() {
  [ -f "$SECRETS_FILE" ] || return 0
  grep -E "^$1=" "$SECRETS_FILE" | tail -n 1 | cut -d= -f2- || true
}

# Guarda una clave en .secrets.env sin tocar las demás. El archivo queda con permisos 600.
write_secret() {
  local key="$1" value="$2" tmp
  mkdir -p "$CF_DIR"
  tmp="$(mktemp "$CF_DIR/.secrets.XXXXXX")"
  if [ -f "$SECRETS_FILE" ]; then grep -v -E "^$key=" "$SECRETS_FILE" > "$tmp" || true; fi
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$SECRETS_FILE"
}

generate_value() {
  "$PY" - "$1" <<'PY'
import secrets, string, sys
if sys.argv[1] == "password":
    alphabet = string.ascii_letters + string.digits
    print("".join(secrets.choice(alphabet) for _ in range(20)))
else:
    print(secrets.token_hex(32))
PY
}

# Genera solo lo que falta. La contraseña del sitio se imprime únicamente cuando se crea.
ensure_secrets() {
  local created=0 password
  if [ -z "$(read_secret SITE_PASSWORD)" ]; then
    password="$(generate_value password)"
    write_secret SITE_PASSWORD "$password"
    created=1
    log "Contraseña del sitio (solo se muestra esta vez): $password"
  fi
  if [ -z "$(read_secret SESSION_SECRET)" ]; then
    write_secret SESSION_SECRET "$(generate_value token)"
    created=1
  fi
  if [ -z "$(read_secret SUBS_API_KEY)" ]; then
    write_secret SUBS_API_KEY "$(generate_value token)"
    created=1
  fi
  if [ "$created" = 1 ]; then log "secretos guardados en $SECRETS_FILE (permisos 600)"; fi
  return 0
}

# Sube un secreto al Worker por stdin, para que el valor no aparezca en la línea de comandos. Vacío = no hace nada.
put_secret() {
  local key="$1" value="$2"
  [ -n "$value" ] || return 0
  printf '%s' "$value" | wrangler secret put "$key" --name "$WORKER_NAME" > /dev/null \
    || die "no se pudo subir el secreto $key al Worker"
  log "secreto $key subido al Worker"
}

deploy_site() {
  wrangler deploy --config "$CF_DIR/wrangler.jsonc"
}

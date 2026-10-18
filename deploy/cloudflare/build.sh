#!/usr/bin/env bash
# Genera deploy/cloudflare/build/ (assets estáticos del Worker): frontend/ sin frontend/dev y _headers tal cual.
# La carpeta es generada y no se versiona. No copia assets/fonts: las fuentes llegan por el Worker, en /fonts/.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
rsync -a --exclude=/dev/ --exclude=.DS_Store "$ROOT/frontend/" "$BUILD_DIR/"
cp "$ROOT/frontend/_headers" "$BUILD_DIR/_headers"

# Ningún secreto debe acabar dentro del paquete público.
for key in SITE_PASSWORD SESSION_SECRET SUBS_API_KEY; do
  value="$(read_secret "$key")"
  if [ -n "$value" ] && grep -rqF -- "$value" "$BUILD_DIR"; then
    die "el valor de $key aparece dentro del paquete; no se despliega"
  fi
done
log "paquete listo en $BUILD_DIR ($(find "$BUILD_DIR" -type f | wc -l | tr -d ' ') archivos)"

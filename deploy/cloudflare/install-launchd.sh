#!/usr/bin/env bash
# Instala, quita o muestra los dos LaunchAgents del sitio: el backend (uvicorn en 8765) y el túnel rápido.
# Los agentes apuntan a este clon y a SUBS_DATA_DIR (por defecto ~/Services/clickflow-subs-data). Un clon dentro de
# Documents, Desktop o Downloads no sirve: launchd no tiene acceso a esas carpetas.
# Uso: install-launchd.sh [install|uninstall|status]
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=("com.clickflow.subs" "com.clickflow.subs-tunnel")
TEMPLATES=("$CF_DIR/launchd/com.clickflow.subs.plist.template" "$CF_DIR/launchd/com.clickflow.subs-tunnel.plist.template")
DATA="${SUBS_DATA_DIR:-$HOME/Services/clickflow-subs-data}"

case "$ROOT" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    die "el clon está en $ROOT: launchd no puede leer esa carpeta (TCC). Usa un clon en ~/Services." ;;
esac

case "${1:-status}" in
  install)
    mkdir -p "$DATA/logs" "$AGENTS"
    for label in "${LABELS[@]}"; do launchctl bootout "$DOMAIN/$label" 2>/dev/null || true; done
    if lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN > /dev/null 2>&1; then
      die "el puerto $BACKEND_PORT sigue ocupado: para el backend a mano antes de instalar"
    fi
    for i in 0 1; do
      dest="$AGENTS/${LABELS[$i]}.plist"
      sed -e "s|__ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" -e "s|__DATA__|$DATA|g" "${TEMPLATES[$i]}" > "$dest"
      launchctl bootstrap "$DOMAIN" "$dest"
      log "cargado ${LABELS[$i]} (datos en $DATA)"
    done
    ;;
  uninstall)
    for label in "${LABELS[@]}"; do
      launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
      rm -f "$AGENTS/$label.plist"
      log "quitado $label"
    done
    ;;
  status)
    for label in "${LABELS[@]}"; do
      if info="$(launchctl print "$DOMAIN/$label" 2>/dev/null)"; then
        pid="$(printf '%s\n' "$info" | awk '/^[ \t]*pid = /{print $3; exit}')"
        prog="$(printf '%s\n' "$info" | awk -F' = ' '/^[ \t]*program = /{print $2; exit}')"
        log "$label: cargado, pid ${pid:-ninguno}, programa $prog"
      else
        log "$label: no cargado"
      fi
    done
    ;;
  *) die "uso: install-launchd.sh [install|uninstall|status]" ;;
esac

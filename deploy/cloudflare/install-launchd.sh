#!/usr/bin/env bash
# Instala, quita o muestra los dos LaunchAgents del sitio: el backend (uvicorn en 8765) y el túnel rápido.
# Uso: install-launchd.sh [install|uninstall|status]
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=("com.clickflow.subs" "com.clickflow.subs-tunnel")
TEMPLATES=("$CF_DIR/launchd/com.clickflow.subs.plist.template" "$CF_DIR/launchd/com.clickflow.subs-tunnel.plist.template")

case "${1:-status}" in
  install)
    mkdir -p "$LOG_DIR" "$AGENTS"
    for i in 0 1; do
      dest="$AGENTS/${LABELS[$i]}.plist"
      sed -e "s|__ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" "${TEMPLATES[$i]}" > "$dest"
      launchctl bootout "$DOMAIN/${LABELS[$i]}" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$dest"
      log "cargado ${LABELS[$i]}"
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
      if launchctl print "$DOMAIN/$label" > /dev/null 2>&1; then log "$label: cargado"; else log "$label: no cargado"; fi
    done
    ;;
  *) die "uso: install-launchd.sh [install|uninstall|status]" ;;
esac

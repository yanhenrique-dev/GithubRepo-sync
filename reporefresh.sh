#!/usr/bin/env bash
# RepoRefresh: sobe o servidor, abre o navegador, ícone na bandeja.
# Uso: ./reporefresh.sh [porta]
set -euo pipefail
DIR="$(dirname "$0")"
cd "$DIR"
if [ -x "$DIR/.venv/bin/python" ]; then
  exec "$DIR/.venv/bin/python" "$DIR/tray.py" "${1:-${REPOREFRESH_PORT:-8000}}"
fi
exec ./tray.py "${1:-${REPOREFRESH_PORT:-8000}}"

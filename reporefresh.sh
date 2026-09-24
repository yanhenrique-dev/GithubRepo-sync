#!/usr/bin/env bash
# RepoRefresh: sobe o servidor, abre o navegador, ícone na bandeja.
# Uso: ./reporefresh.sh [porta]
set -euo pipefail
DIR="$(dirname "$0")"
cd "$DIR"
if [ "$#" -gt 0 ]; then
  if [ -x "$DIR/.venv/bin/python" ]; then
    exec "$DIR/.venv/bin/python" "$DIR/tray.py" "$1"
  fi
  exec ./tray.py "$1"
fi
if [ -x "$DIR/.venv/bin/python" ]; then
  exec "$DIR/.venv/bin/python" "$DIR/tray.py"
fi
exec ./tray.py

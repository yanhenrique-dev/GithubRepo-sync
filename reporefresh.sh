#!/usr/bin/env bash
# RepoRefresh: sobe o servidor, abre o navegador, ícone na bandeja.
# Uso: ./reporefresh.sh [porta]
set -euo pipefail
cd "$(dirname "$0")"
exec ./tray.py "${1:-${REPOREFRESH_PORT:-8000}}"

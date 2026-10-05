#!/usr/bin/env bash
# Lance neronOS Core depuis ce clone (dev / test hors systemd).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"

[ -x "$PY" ] || {
  echo "venv introuvable dans $ROOT/.venv" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r system/requirements/core.txt" >&2
  exit 1
}

# Variables communes (chemins /etc/neronOS), puis redirection vers ce clone
set -a
[ -f "$ROOT/system/deploy/env/common.env" ] && source "$ROOT/system/deploy/env/common.env"
set +a

export NERON_ROOT="$ROOT"
export PYTHONPATH="$ROOT:$ROOT/server"

cd "$ROOT/server"
exec "$PY" -m common.serve core

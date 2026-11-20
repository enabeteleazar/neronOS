#!/usr/bin/env bash
# Lance un module NéronOS hors systemd (développement, test, dépannage).
#
# Usage : system/scripts/start-module.sh <module>
#   module : core llm memory goal voice gateways doctor print watchdog
#            (tout nœud de la section `nodes` de neron.server.yaml)
#
# Fait exactement ce que fait l'unité systemd neron@<module>.service :
# `python -m common.serve <module>`, qui lit l'adresse et le port du nœud dans
# neron.server.yaml. Seules différences : la racine est CE clone (et non
# /etc/neronOS), et l'environnement vient de env/common.env + secrets.env du
# clone s'ils existent.
#
# Variables :
#   NERON_VENV  environnement Python (défaut : <racine>/.venv, sinon <racine>/venv)
#   NERON_ROOT  racine NéronOS (défaut : ce clone)
#
# Les modules autres que core doivent être présents sous server/<module> :
# voir system/scripts/setup-modules.sh.
set -euo pipefail

MODULE="${1:-}"
[ -n "$MODULE" ] || { echo "usage : $0 <module>" >&2; exit 2; }

ROOT="${NERON_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if [ -n "${NERON_VENV:-}" ]; then VENV="$NERON_VENV"
elif [ -x "$ROOT/.venv/bin/python" ]; then VENV="$ROOT/.venv"
else VENV="$ROOT/venv"
fi
# Chemin absolu : le script change de dossier avant de lancer Python.
[ -d "$VENV" ] && VENV="$(cd "$VENV" && pwd)"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  echo "environnement Python introuvable : $VENV" >&2
  echo "  system/scripts/setup-modules.sh --venv    (ou NERON_VENV=/chemin/du/venv)" >&2
  exit 1
fi

if ! grep -qE "^  ${MODULE}:" "$ROOT/neron.server.yaml" 2>/dev/null; then
  echo "module inconnu : '$MODULE' n'est pas un nœud de $ROOT/neron.server.yaml" >&2
  exit 1
fi
if [ "$MODULE" != core ] && [ ! -f "$ROOT/server/$MODULE/app.py" ]; then
  echo "module '$MODULE' absent : $ROOT/server/$MODULE/app.py introuvable" >&2
  echo "  system/scripts/setup-modules.sh $MODULE" >&2
  exit 1
fi

# Environnement commun (chemins /etc/neronOS), puis secrets du clone s'il en a,
# puis redirection vers ce clone.
set -a
[ -f "$ROOT/system/deploy/env/common.env" ] && . "$ROOT/system/deploy/env/common.env"
[ -f "$ROOT/secrets.env" ] && . "$ROOT/secrets.env"
set +a
export NERON_ROOT="$ROOT"
export NERON_CONFIG="$ROOT/neron.yaml"
export PYTHONPATH="$ROOT:$ROOT/server"

if [ -z "${NERON_API_KEY:-}" ] && [ "$MODULE" != core ]; then
  echo "attention : NERON_API_KEY absente — memory et voice répondront 503, les autres" >&2
  echo "            services refuseront les appels authentifiés du Core." >&2
fi

cd "$ROOT/server"
exec "$PY" -m common.serve "$MODULE"

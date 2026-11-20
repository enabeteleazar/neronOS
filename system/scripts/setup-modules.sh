#!/usr/bin/env bash
# Met en place les modules de NéronOS sous server/, puis (option) l'environnement Python.
#
# Depuis le 16/10, neronOS n'a plus de sous-modules : LLM, Memory, Goal, Voice,
# Gateways et Doctor sont des dépôts séparés. Le lanceur unique
# (`python -m common.serve <module>`, cf. system/deploy/systemd/neron@.service)
# importe pourtant `<module>.app` depuis server/ : chaque module doit donc être
# présent sous server/<module>. Ce script le fait, de façon idempotente.
#
# Usage :
#   system/scripts/setup-modules.sh [options] [module...]
#
#   (sans option)      clone chaque module manquant depuis GitHub, met à jour
#                      les clones existants (avance rapide uniquement)
#   --link DIR         au lieu de cloner, crée des liens vers des clones locaux
#                      existants (DIR/neronLLM, DIR/neronMemory…) : pratique en
#                      développement, ex. --link /srv/Neron
#   --branch NOM       branche à utiliser (défaut : develop)
#   --venv [DIR]       crée ou met à jour l'environnement Python et installe les
#                      dépendances (défaut : ./venv s'il existe, sinon ./.venv)
#   --check            n'affiche que l'état, ne modifie rien
#   -h, --help         cette aide
#
#   module...          parmi : llm memory goal voice gateways doctor (défaut : tous)
#
# Variables : NERON_GIT_BASE (défaut git@github.com:enabeteleazar), PYTHON (défaut python3).
#
# Exemples :
#   Homebox :   sudo -u neron /etc/neronOS/system/scripts/setup-modules.sh --venv /etc/neronOS/venv
#   Dev local : system/scripts/setup-modules.sh --link /srv/Neron --venv
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GIT_BASE="${NERON_GIT_BASE:-git@github.com:enabeteleazar}"
PYTHON="${PYTHON:-python3}"
BRANCH="develop"
LINK_DIR=""
CHECK=0
SETUP_VENV=0
VENV=""
MODULES=()

declare -A REPOS=(
  [llm]=neronLLM
  [memory]=neronMemory
  [goal]=neronGoal
  [voice]=neronVoice
  [gateways]=neronGateways
  [doctor]=neronDoctor
)
ALL_MODULES=(llm memory goal voice gateways doctor)

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; }
info() { printf '  %-10s %s\n' "$1" "$2"; }
die()  { echo "erreur : $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --link)   [ $# -ge 2 ] || die "--link attend un dossier"; LINK_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --branch) [ $# -ge 2 ] || die "--branch attend un nom"; BRANCH="$2"; shift 2 ;;
    --venv)
      SETUP_VENV=1
      if [ $# -ge 2 ] && [ "${2#-}" = "$2" ] && [ -z "${REPOS[$2]+x}" ]; then VENV="$2"; shift; fi
      shift ;;
    --check)  CHECK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "option inconnue : $1 (voir --help)" ;;
    *)  [ -n "${REPOS[$1]+x}" ] || die "module inconnu : $1 (attendus : ${ALL_MODULES[*]})"
        MODULES+=("$1"); shift ;;
  esac
done
[ ${#MODULES[@]} -gt 0 ] || MODULES=("${ALL_MODULES[@]}")

echo "NéronOS : $ROOT"
echo "Modules : ${MODULES[*]} (branche $BRANCH$([ -n "$LINK_DIR" ] && echo ", liens vers $LINK_DIR"))"
RC=0

setup_module() {
  local module="$1" repo="${REPOS[$1]}" target="$ROOT/server/$1"

  if [ "$CHECK" -eq 1 ]; then
    if [ -L "$target" ]; then info "$module" "lien -> $(readlink "$target")"
    elif [ -d "$target/.git" ]; then
      info "$module" "clone, branche $(git -C "$target" branch --show-current), $(git -C "$target" status --short | wc -l) modif."
    elif [ -e "$target" ]; then info "$module" "PRÉSENT MAIS NI LIEN NI CLONE"; RC=1
    else info "$module" "MANQUANT"; RC=1
    fi
    return
  fi

  if [ -n "$LINK_DIR" ]; then
    local source="$LINK_DIR/$repo"
    [ -d "$source" ] || { info "$module" "ignoré : $source introuvable"; RC=1; return; }
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      info "$module" "ignoré : $target existe déjà et n'est pas un lien (rien n'est écrasé)"; RC=1; return
    fi
    ln -sfn "$source" "$target"
    info "$module" "lien -> $source"
    return
  fi

  if [ -L "$target" ]; then
    info "$module" "lien existant conservé -> $(readlink "$target")"
  elif [ -d "$target/.git" ]; then
    if [ -n "$(git -C "$target" status --porcelain)" ]; then
      info "$module" "non mis à jour : modifications locales"; RC=1; return
    fi
    if ! git -C "$target" fetch --quiet origin || ! git -C "$target" checkout --quiet "$BRANCH"; then
      info "$module" "non mis à jour : fetch ou checkout de $BRANCH impossible"; RC=1; return
    fi
    if git -C "$target" merge --quiet --ff-only "origin/$BRANCH" 2>/dev/null; then
      info "$module" "à jour ($(git -C "$target" log -1 --format=%h))"
    else
      info "$module" "non mis à jour : $BRANCH a divergé de origin/$BRANCH"; RC=1
    fi
  elif [ -e "$target" ]; then
    info "$module" "ignoré : $target existe et n'est pas un clone git (rien n'est écrasé)"; RC=1
  else
    if git clone --quiet --branch "$BRANCH" "$GIT_BASE/$repo.git" "$target"; then
      info "$module" "cloné ($(git -C "$target" log -1 --format=%h))"
    else
      info "$module" "échec du clone de $GIT_BASE/$repo.git (accès, réseau ou branche $BRANCH ?)"; RC=1
    fi
  fi
}

for module in "${MODULES[@]}"; do setup_module "$module"; done

if [ -n "$LINK_DIR" ] && [ "$CHECK" -eq 0 ] && printf '%s\n' "${MODULES[@]}" | grep -qx memory; then
  echo
  echo "  Attention (mode lien) : Memory écrit sa base et ses notes Obsidian dans"
  echo "  $LINK_DIR/neronMemory. La base est ignorée par git, pas les notes."
fi

if [ "$SETUP_VENV" -eq 1 ] && [ "$CHECK" -eq 0 ]; then
  if [ -z "$VENV" ]; then
    if [ -d "$ROOT/venv" ]; then VENV="$ROOT/venv"; else VENV="$ROOT/.venv"; fi
  fi
  echo
  echo "Environnement Python : $VENV"
  [ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet --prefer-binary \
    -r "$ROOT/system/requirements/requirements.txt" \
    -r "$ROOT/system/requirements/memory.txt" \
    --constraint "$ROOT/system/requirements/constraints.txt"
  echo "  dépendances installées"
fi

echo
missing=()
for module in "${MODULES[@]}"; do
  [ -f "$ROOT/server/$module/app.py" ] || missing+=("$module")
done
if [ ${#missing[@]} -eq 0 ]; then
  echo "Prêt. Démarrage d'un module : system/scripts/start-module.sh <module>"
else
  echo "Modules incomplets (pas de server/<module>/app.py) : ${missing[*]}"; RC=1
fi
exit $RC

#!/usr/bin/env bash
# rotate_secrets.sh (v2) — rotation des secrets neronOS sans jamais afficher une valeur.
#
# Usage :
#   sudo bash rotate_secrets.sh check      # liste les copies de secrets.env trouvées (droits, clés)
#   sudo bash rotate_secrets.sh auto       # régénère NERON_API_KEY + NERON_DOCTOR_API_KEY partout
#   sudo bash rotate_secrets.sh set CLE    # saisie masquée d'une nouvelle valeur (tokens tiers)
#   sudo bash rotate_secrets.sh db         # change le mot de passe PostgreSQL + DATABASE_URL
#
# Découverte : tous les fichiers nommés `secrets.env` sous /etc/neronOS /srv /opt /home
# (node_modules, .venv et .git ignorés ; les liens symboliques sont résolus et dédoublonnés).
#   Racines personnalisées : NERON_SCAN_ROOTS="/chemin1 /chemin2"
#   Liste forcée           : NERON_SECRETS_FILES="/a/secrets.env:/b/secrets.env"
#
# PostgreSQL hors machine / dans Docker :
#   sudo PSQL_CMD="docker exec -i <conteneur> psql -U postgres" bash rotate_secrets.sh db
#
# Une seule sauvegarde par fichier et par exécution (*.bak.<date>, mode 600). Elle contient
# les ANCIENNES valeurs compromises : à détruire avec `shred -u` après validation.

set -euo pipefail
umask 077

if [[ $EUID -ne 0 ]]; then
  # Pas de -E (non supporté par sudo-rs) : lance toujours le script avec `sudo`,
  # et passe les variables explicitement : sudo VAR=valeur bash rotate_secrets.sh …
  echo "Ce script doit tourner en root : relance-le avec  sudo bash $0 $*" >&2
  exit 1
fi

FILES=()
discover() {
  if [[ -n "${NERON_SECRETS_FILES:-}" ]]; then
    local IFS=':'
    read -r -a FILES <<< "$NERON_SECRETS_FILES"
    return
  fi
  # shellcheck disable=SC2206
  local roots=(${NERON_SCAN_ROOTS:-/etc/neronOS /srv /opt /home})
  local f
  local -A seen=()
  while IFS= read -r -d '' f; do
    f="$(readlink -f "$f" 2>/dev/null || true)"
    [[ -n "$f" && -f "$f" ]] || continue
    if [[ -z "${seen[$f]:-}" ]]; then seen[$f]=1; FILES+=("$f"); fi
  done < <(find "${roots[@]}" -xdev -maxdepth 7 \
             \( -name node_modules -o -name .venv -o -name .git \) -prune -o \
             \( -type f -o -type l \) -name secrets.env -print0 2>/dev/null || true)
}

has_key() { grep -qE "^[[:space:]]*(export[[:space:]]+)?$2=" "$1"; }

# set_in_file FICHIER CLE  (la valeur passe par l'environnement NEW_VALUE,
# jamais en argument, pour ne pas apparaître dans `ps`)
set_in_file() {
  python3 - "$1" "$2" <<'PY'
import os, re, sys
path, key = sys.argv[1], sys.argv[2]
value = os.environ["NEW_VALUE"]
with open(path) as fh:
    lines = fh.read().split("\n")
pat = re.compile(r"^\s*(export\s+)?" + re.escape(key) + r"\s*=")
out, hit = [], False
for line in lines:
    if pat.match(line):
        prefix = "export " if line.lstrip().startswith("export ") else ""
        out.append(f"{prefix}{key}={value}")
        hit = True
    else:
        out.append(line)
if not hit:
    sys.exit(3)
with open(path, "w") as fh:  # écrit sur place : propriétaire et groupe conservés
    fh.write("\n".join(out))
PY
}

TS="$(date +%Y%m%d%H%M%S)"
BACKUPS=()
declare -A BACKED=()
backup_once() {
  local f="$1" bk
  if [[ -n "${BACKED[$f]:-}" ]]; then return; fi
  bk="$f.bak.$TS"
  cp -p "$f" "$bk"
  chmod 600 "$bk"
  BACKED[$f]=1
  BACKUPS+=("$bk")
}

apply_key() {
  local key="$1" f n=0
  for f in "${FILES[@]}"; do
    has_key "$f" "$key" || continue
    backup_once "$f"
    set_in_file "$f" "$key"
    chmod 600 "$f"
    echo "  ✔ $key mis à jour dans $f"
    n=$((n + 1))
  done
  if [[ $n -eq 0 ]]; then echo "  ⚠ $key introuvable dans les fichiers ciblés"; fi
}

caddy_hint() {
  local hits
  hits=$(grep -rl "NERON_API_KEY" /etc/systemd/system/caddy.service.d /etc/caddy 2>/dev/null || true)
  echo
  if [[ -n "$hits" ]]; then
    echo "⚠ Caddy injecte NERON_API_KEY. Mets la nouvelle valeur dans :"
    echo "$hits" | sed 's/^/    /'
    echo "  (ou vérifie son EnvironmentFile : systemctl cat caddy)"
  else
    echo "⚠ Vérifie que le service caddy reçoit la NOUVELLE NERON_API_KEY (systemctl cat caddy)."
  fi
}

finish() {
  echo
  echo "Reste à faire :"
  echo "  1. Redémarrer les services : systemctl restart neron.target caddy"
  echo "     (et relancer à la main les processus démarrés hors systemd : start-core.sh, nohup…)"
  echo "  2. Mettre la nouvelle NERON_API_KEY dans les clients qui la stockent (Dashboard, pcRemote, apps)."
  if [[ ${#BACKUPS[@]} -gt 0 ]]; then
    echo "  3. Après validation, détruire les sauvegardes (anciennes valeurs) :"
    printf '       shred -u %s\n' "${BACKUPS[@]}"
  fi
}

cmd_check() {
  local f
  for f in "${FILES[@]}"; do
    echo "$f  [$(stat -c '%a %U:%G' "$f")]"
    if [[ "$(stat -c '%a' "$f")" != "600" ]]; then echo "  ⚠ droits ≠ 600"; fi
    grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Z_]+=.+' "$f" \
      | sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Z_]+)=.*/    \2 (renseignée)/'
  done
  echo
  echo "${#FILES[@]} fichier(s). Toute copie absente de cette liste garde ses anciennes valeurs."
}

cmd_auto() {
  local key
  for key in NERON_API_KEY NERON_DOCTOR_API_KEY; do
    echo "→ $key"
    NEW_VALUE="$(openssl rand -hex 32)" apply_key "$key"
  done
  caddy_hint
  finish
}

cmd_set() {
  local key="${1:-}" value
  if [[ -z "$key" ]]; then echo "usage: $0 set CLE"; exit 2; fi
  read -rsp "Nouvelle valeur pour $key (saisie masquée) : " value; echo
  if [[ -z "$value" ]]; then echo "valeur vide — abandon"; exit 2; fi
  echo "→ $key"
  NEW_VALUE="$value" apply_key "$key"
  finish
}

cmd_db() {
  local f url="" parsed user newpw newurl
  local -a PSQL
  for f in "${FILES[@]}"; do
    if has_key "$f" DATABASE_URL; then
      url=$(grep -E '^[[:space:]]*(export[[:space:]]+)?DATABASE_URL=' "$f" | head -1 | cut -d= -f2-)
      break
    fi
  done
  if [[ -z "$url" ]]; then echo "DATABASE_URL introuvable"; exit 1; fi

  if [[ -n "${PSQL_CMD:-}" ]]; then
    read -r -a PSQL <<< "$PSQL_CMD"
  elif id postgres >/dev/null 2>&1 && command -v psql >/dev/null 2>&1; then
    PSQL=(runuser -u postgres -- psql)
  else
    echo "PostgreSQL local introuvable (utilisateur 'postgres' ou 'psql' absent)."
    echo "S'il tourne dans Docker ou ailleurs :"
    echo "  sudo PSQL_CMD=\"docker exec -i <conteneur> psql -U postgres\" bash $0 db"
    exit 1
  fi

  newpw="$(openssl rand -hex 24)"
  parsed=$(DB_URL="$url" NEW_PW="$newpw" python3 - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(os.environ["DB_URL"])
if not u.username:
    raise SystemExit("DATABASE_URL sans utilisateur")
host = u.hostname or "localhost"
port = f":{u.port}" if u.port else ""
new = urlunsplit((u.scheme, f"{u.username}:{os.environ['NEW_PW']}@{host}{port}", u.path, u.query, u.fragment))
print(u.username)
print(new)
PY
)
  user=$(sed -n 1p <<< "$parsed")
  newurl=$(sed -n 2p <<< "$parsed")
  echo "→ ALTER ROLE \"$user\" (PostgreSQL)"
  # D'abord la base : si ça échoue, aucun fichier n'est modifié (set -e).
  "${PSQL[@]}" -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$user\" PASSWORD '$newpw';" >/dev/null
  echo "→ DATABASE_URL"
  NEW_VALUE="$newurl" apply_key DATABASE_URL
  finish
}

discover
if [[ ${#FILES[@]} -eq 0 ]]; then echo "Aucun secrets.env trouvé."; exit 1; fi

case "${1:-}" in
  check) cmd_check ;;
  auto)  cmd_auto ;;
  set)   shift; cmd_set "${1:-}" ;;
  db)    cmd_db ;;
  *) sed -n '2,19p' "$0"; exit 2 ;;
esac

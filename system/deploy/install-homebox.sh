#!/usr/bin/env bash
# Installation complète de NéronOS sur la Homebox, en service permanent (systemd).
#
# À lancer en root :   sudo system/deploy/install-homebox.sh [--dry-run] [SOURCE]
#
#   SOURCE     dossier contenant les clones neronOS, neronLLM, neronMemory…
#              (défaut : /srv/Neron). Le code est cloné DEPUIS ces dépôts
#              locaux : l'utilisateur de service `neron` n'a pas de clé GitHub.
#   --dry-run  affiche les commandes sans rien exécuter.
#
# Idempotent : chaque étape vérifie ce qui est déjà en place.
#
#   1. paquets système : bubblewrap (isolation du code généré), git, python3-venv
#   2. utilisateur de service neron, groupe neron-dev (cf. neron@.service)
#   3. code neronOS dans /etc/neronOS, branche develop
#   4. modules sous /etc/neronOS/server + environnement Python /etc/neronOS/venv
#   5. secrets : /etc/neronOS/secrets.env (repris de SOURCE/neronOS/secrets.env)
#   6. modèle d'intentions CamemBERT dans le cache de neron
#   7. Ollama (service officiel) et modèles de neron.yaml
#   8. configuration systemd et Caddy (install.sh), clé d'API pour Caddy
#   9. démarrage de neron.target et état des services
set -euo pipefail

DRY=0
SOURCE=/srv/Neron
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) SOURCE="$arg" ;;
  esac
done

DEST=/etc/neronOS
SERVICE_USER=neron
SERVICE_GROUP=neron-dev
ADMIN_USER="${SUDO_USER:-}"
MODELS=(qwen3.5:2b qwen2.5-coder:1.5b)   # modèles cités par neron.yaml (llm.model, tasks)

step() { printf '\n== %s\n' "$*"; }
run() {
  printf '   $ %s\n' "$*"
  [ "$DRY" -eq 1 ] || "$@"
}
as_neron() { run sudo -u "$SERVICE_USER" -H "$@"; }

[ "$DRY" -eq 1 ] || [ "$(id -u)" -eq 0 ] || { echo "à lancer avec sudo (ou --dry-run)" >&2; exit 1; }
[ -d "$SOURCE/neronOS/.git" ] || { echo "dépôt introuvable : $SOURCE/neronOS" >&2; exit 1; }

step "1. Paquets système"
missing=()
for pkg in bubblewrap git python3-venv curl; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ ${#missing[@]} -gt 0 ]; then
  run apt-get update -qq
  run apt-get install -y "${missing[@]}"
else
  echo "   déjà installés"
fi

step "2. Utilisateur de service"
getent group "$SERVICE_GROUP" >/dev/null || run groupadd --system "$SERVICE_GROUP"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  run useradd --system --create-home --home-dir "/home/$SERVICE_USER" \
      --gid "$SERVICE_GROUP" --shell /usr/sbin/nologin "$SERVICE_USER"
else
  echo "   $SERVICE_USER existe déjà"
fi
[ -n "$ADMIN_USER" ] && run usermod -aG "$SERVICE_GROUP" "$ADMIN_USER"
# Les clones source appartiennent à un autre utilisateur : git exige de les
# déclarer sûrs pour que neron puisse les cloner et les mettre à jour.
for name in neronOS neronLLM neronMemory neronGoal neronVoice neronGateways neronDoctor; do
  repo="$SOURCE/$name"
  [ -d "$repo/.git" ] || continue
  if ! sudo -u "$SERVICE_USER" -H git config --global --get-all safe.directory 2>/dev/null | grep -qx "$repo"; then
    as_neron git config --global --add safe.directory "$repo"
  fi
done

step "3. Code neronOS dans $DEST"
run mkdir -p "$DEST"
if [ ! -d "$DEST/.git" ]; then
  # $DEST peut déjà contenir env/ (posé par install.sh) : init + checkout
  # plutôt que clone, qui refuse un dossier non vide.
  run git -C "$DEST" init -q
  run git -C "$DEST" remote add origin "$SOURCE/neronOS"
fi
run chown -R "$SERVICE_USER:$SERVICE_GROUP" "$DEST"
as_neron git -C "$DEST" fetch -q origin develop
if [ "$DRY" -eq 1 ] || [ -z "$(sudo -u "$SERVICE_USER" git -C "$DEST" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  as_neron git -C "$DEST" checkout -q -B develop origin/develop
else
  echo "   modifications locales dans $DEST : checkout ignoré" >&2
fi

step "4. Modules et environnement Python"
as_neron env NERON_GIT_BASE="$SOURCE" "$DEST/system/scripts/setup-modules.sh" --venv "$DEST/venv"

step "5. Secrets"
if [ -f "$DEST/secrets.env" ]; then
  echo "   $DEST/secrets.env existe déjà : conservé"
elif [ -f "$SOURCE/neronOS/secrets.env" ]; then
  run install -m 0640 -o root -g "$SERVICE_GROUP" "$SOURCE/neronOS/secrets.env" "$DEST/secrets.env"
else
  echo "   ATTENTION : aucun secrets.env — Memory et Voice répondront 503" >&2
fi

step "6. Modèle d'intentions CamemBERT"
cache_src="${ADMIN_USER:+/home/$ADMIN_USER}/.cache/huggingface/hub/models--almanach--camembert-base"
cache_dst="/home/$SERVICE_USER/.cache/huggingface/hub"
if [ -d "$cache_dst/models--almanach--camembert-base" ]; then
  echo "   déjà présent"
elif [ -n "$ADMIN_USER" ] && [ -d "$cache_src" ]; then
  run mkdir -p "$cache_dst"
  run cp -a "$cache_src" "$cache_dst/"
  run chown -R "$SERVICE_USER:$SERVICE_GROUP" "/home/$SERVICE_USER/.cache"
else
  as_neron "$DEST/venv/bin/huggingface-cli" download almanach/camembert-base
fi

step "7. Ollama et modèles"
if pgrep -u "${ADMIN_USER:-nobody}" -f "ollama serve" >/dev/null 2>&1; then
  echo "   ATTENTION : un Ollama tourne sous $ADMIN_USER (port 11434) : arrête-le avant," >&2
  echo "   sinon le service Ollama du système ne pourra pas démarrer." >&2
fi
if ! command -v ollama >/dev/null 2>&1; then
  run sh -c 'curl -fsSL https://ollama.com/install.sh | sh'
fi
for model in "${MODELS[@]}"; do
  if [ "$DRY" -eq 0 ] && ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model"; then
    echo "   $model déjà présent"
  else
    run ollama pull "$model"
  fi
done

step "8. systemd et Caddy"
run "$DEST/system/deploy/install.sh" install
# Caddy injecte NERON_API_KEY vers le Core, Memory et Voice (cf. Caddyfile).
dropin=/etc/systemd/system/caddy.service.d/neron.conf
if [ ! -f "$dropin" ]; then
  run mkdir -p "$(dirname "$dropin")"
  if [ "$DRY" -eq 1 ]; then
    echo "   (écrirait $dropin : EnvironmentFile=-$DEST/secrets.env)"
  else
    printf '[Service]\nEnvironmentFile=-%s/secrets.env\n' "$DEST" > "$dropin"
  fi
  run systemctl daemon-reload
  run systemctl restart caddy
fi

step "9. Démarrage"
# neron.target démarre aussi neron@print, mais le dépôt neronPrint ne contient
# pas encore de service : sans module, le masquer évite une boucle de
# redémarrages en échec. Réversible : systemctl unmask neron@print.service
if [ ! -f "$DEST/server/print/app.py" ] && [ "$(systemctl is-enabled neron@print.service 2>/dev/null)" != masked ]; then
  run systemctl mask neron@print.service
fi
run systemctl enable --now neron.target
if [ "$DRY" -eq 0 ]; then
  sleep 15
  for unit in core llm memory goal voice gateways doctor; do
    printf '   neron@%-9s %s\n' "$unit" "$(systemctl is-active "neron@$unit.service" || true)"
  done
  echo
  echo "Vérification complète : make -C $DEST health"
fi

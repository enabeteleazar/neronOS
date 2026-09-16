#!/usr/bin/env bash
#
# contention_report.sh - Audit de contention systeme, STRICTEMENT LECTURE SEULE.
#
# Ce script n'arrete aucun processus, ne tue rien, ne redemarre aucun service,
# ne modifie aucune configuration, ne touche ni a NeronOS ni a Ollama.
# Il n'execute aucun benchmark et ne collecte aucune mesure LLM.
#
# Usage:
#   ./scripts/contention_report.sh                 # rapport sur stdout
#   ./scripts/contention_report.sh --out FICHIER   # rapport aussi ecrit dans FICHIER
#   ./scripts/contention_report.sh --top 30        # nombre de processus detailles
#
# Toute information non determinable est signalee explicitement par "INDETERMINE".

TOPN=20
OUT=""

for arg in "$@"; do
  case "$arg" in
    --out) shift; OUT="${1:-}" ;;
    --out=*) OUT="${arg#*=}" ;;
    --top) shift; TOPN="${1:-20}" ;;
    --top=*) TOPN="${arg#*=}" ;;
  esac
  shift 2>/dev/null || true
done

if [ -n "$OUT" ]; then
  exec > >(tee "$OUT") 2>&1
fi

BOLD="\033[1m"; BLUE="\033[34m"; NC="\033[0m"
step(){ echo -e "\n${BOLD}${BLUE}━━━ $1 ━━━${NC}"; }
na(){ echo "INDETERMINE : $1"; }
have(){ command -v "$1" >/dev/null 2>&1; }

# Ecarte le script lui-meme et ses ancetres : sa propre ligne de commande contient
# les motifs recherches (migrat, node, ...) et produirait de faux positifs.
SELF_PIDS=" $$ $PPID "
p=$PPID; for _ in 1 2 3 4; do
  p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' '); [ -z "$p" ] && break
  SELF_PIDS="$SELF_PIDS$p "
done
exclude_self(){ # filtre une liste de PID sur stdin
  while read -r pid; do
    [ -n "$pid" ] || continue
    case "$SELF_PIDS" in *" $pid "*) continue ;; esac
    grep -qs 'contention_report\.sh' "/proc/$pid/cmdline" 2>/dev/null && continue
    echo "$pid"
  done
}

NCPU=$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo)

# =========================================================================
step "0. CONTEXTE"
# =========================================================================
echo "Date            : $(date -Is)"
echo "Hote            : $(hostname)"
echo "Noyau           : $(uname -sr)"
echo "PID 1           : $(cat /proc/1/comm 2>/dev/null)"
echo "Uptime          : $(uptime -p 2>/dev/null || cut -d' ' -f1 /proc/uptime)"
echo "vCPU            : $NCPU"
echo "Mode            : LECTURE SEULE (aucune modification, aucun arret)"
if [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ]; then
  echo "AVERTISSEMENT   : PID 1 n'est pas systemd -> les sections systemd seront partielles."
fi

# =========================================================================
step "5. CPU / CHARGE / SATURATION (CPU vs I/O vs memoire)"
# =========================================================================
echo "loadavg         : $(cat /proc/loadavg)"
awk -v n="$NCPU" '{printf "Charge par CPU  : %.2f (1min) / %.2f (5min) - seuil de saturation = 1.00\n", $1/n, $2/n}' /proc/loadavg
echo
echo "-- Repartition CPU instantanee (3 echantillons) --"
if have vmstat; then vmstat 1 3; else na "vmstat absent"; fi
echo
echo "-- Pression PSI (some = ralenti, full = totalement bloque) --"
for f in cpu io memory; do
  if [ -r /proc/pressure/$f ]; then
    echo "[$f]"; cat /proc/pressure/$f
  else
    na "/proc/pressure/$f illisible (noyau sans PSI ?)"
  fi
done
echo
echo "-- Files d'attente --"
grep -E "procs_running|procs_blocked" /proc/stat
echo "Threads totaux  : $(ps -eLo pid= 2>/dev/null | wc -l)"
echo "Processus       : $(ps -eo pid= | wc -l)"
echo
echo "-- Memoire --"
free -h
echo "Swap in/out cumules :"; grep -E "^(pswpin|pswpout)" /proc/vmstat
echo
echo "-- I/O par peripherique --"
if have iostat; then iostat -x 1 2 | tail -n +4; else na "iostat absent (paquet sysstat)"; fi
echo
echo "LECTURE : load eleve + %wa eleve + PSI io.full eleve  => contention I/O."
echo "          load eleve + %us/%sy eleve + PSI cpu eleve  => contention CPU."
echo "          %st non nul                                 => vol de CPU par l'hyperviseur."
echo "          PSI memory non nul ou swap actif            => contention memoire."

# =========================================================================
step "1+2. INVENTAIRE - TOP $TOPN CPU (PID/PPID/user/threads/etat/duree)"
# =========================================================================
ps -eo pid,ppid,user,pcpu,pmem,rss,nlwp,stat,etime,time,args --sort=-pcpu | head -n $((TOPN+1))

step "1+2. INVENTAIRE - TOP $TOPN RAM"
ps -eo pid,ppid,user,pcpu,pmem,rss,nlwp,stat,etime,time,args --sort=-rss | head -n $((TOPN+1))

# =========================================================================
step "2. FICHE DETAILLEE + CLASSIFICATION DES PROCESSUS SIGNIFICATIFS"
# =========================================================================
echo "Criteres de retenue : CPU >= 5% ou RSS >= 200 Mio."
echo "Classification par chemin d'executable / unite systemd / cwd - jamais par le nom seul."
echo

# Classification. On ne se fie JAMAIS au nom du processus ni a une occurrence
# du mot "neron" quelque part dans la ligne de commande : un outil tiers lance
# depuis le depot ou avec --add-dir /chemin/neronOS n'appartient pas a NeronOS.
# Seuls font foi : l'executable reel, le cwd, l'unite systemd, l'utilisateur.
classify(){ # $1=pid $2=exe $3=unit $4=user $5=cmd
  local pid="$1" exe="$2" unit="$3" user="$4" cmd="$5"
  [ -z "$exe" ] && { echo "SYSTEME (thread noyau)"; return; }
  case "$unit" in
    neron*|kula*) echo "NERONOS (unite $unit)"; return ;;
    ollama*) echo "EXTERNE (Ollama - dependance, service distinct)"; return ;;
  esac
  case "$exe" in
    */ollama*) echo "EXTERNE (Ollama - dependance, service distinct)"; return ;;
    /opt/neron*|/etc/neron*|/usr/local/neron*|*/neronOS/*|*/neron/*)
      echo "NERONOS (executable $exe)"; return ;;
  esac
  [ "$user" = "neron" ] && { echo "NERONOS (utilisateur neron)"; return; }
  case "$exe" in
    /usr/lib/systemd/*|/lib/systemd/*|/usr/sbin/*|/sbin/*) echo "SYSTEME"; return ;;
  esac
  [ -n "$unit" ] && [ "$unit" != "-" ] && { echo "EXTERNE (unite $unit)"; return; }
  echo "INCONNU"
}

ps -eo pid=,pcpu=,rss= | while read -r pid pcpu rss; do
  cpu_i=${pcpu%%.*}
  [ "${cpu_i:-0}" -ge 5 ] 2>/dev/null || [ "${rss:-0}" -ge 204800 ] 2>/dev/null || continue
  exe=$(readlink "/proc/$pid/exe" 2>/dev/null)
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null)
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  [ -z "$cmd" ] && cmd="[$(cat "/proc/$pid/comm" 2>/dev/null)] (thread noyau)"
  read -r ppid user nlwp stat etime time _ < <(ps -o ppid=,user=,nlwp=,stat=,etime=,time= -p "$pid" 2>/dev/null)
  parent=$(ps -o comm= -p "${ppid:-0}" 2>/dev/null)
  unit="-"
  if have systemctl && [ -r "/proc/$pid/cgroup" ]; then
    unit=$(grep -o '[^/]*\.service' "/proc/$pid/cgroup" 2>/dev/null | head -1)
    [ -z "$unit" ] && unit="-"
  fi
  echo "----------------------------------------------------------------"
  echo "PID        : $pid"
  echo "PPID       : ${ppid:-?}  (parent: ${parent:-INDETERMINE})"
  echo "Utilisateur: ${user:-INDETERMINE}"
  echo "Commande   : $cmd"
  echo "Executable : ${exe:-INDETERMINE (thread noyau ou /proc illisible)}"
  echo "Cwd        : ${cwd:-INDETERMINE}"
  echo "CPU %      : $pcpu   (moyenne depuis le demarrage du processus)"
  echo "RSS        : $((rss/1024)) Mio"
  echo "Threads    : ${nlwp:-?}   Etat: ${stat:-?}   Elapsed: ${etime:-?}   CPU time: ${time:-?}"
  echo "Unite sysd : $unit"
  echo "Categorie  : $(classify "$pid" "$exe" "$unit" "${user:-}" "$cmd")"
done

# =========================================================================
step "9. ARBRE DES PROCESSUS"
# =========================================================================
if have pstree; then
  pstree -aupT 2>/dev/null || pstree -aup
else
  na "pstree absent - repli sur ps -ejH"
  ps -ejH -o pid,ppid,user,pcpu,args | head -120
fi

# =========================================================================
step "3. AGREGATS PAR UTILISATEUR (part reelle de la contention)"
# =========================================================================
printf "%-14s %7s %9s %11s %9s\n" "UTILISATEUR" "PROCS" "THREADS" "CPU_CUMUL%" "RSS_Mio"
ps -eo user=,pcpu=,rss=,nlwp= | awk '
  { p[$1]++; c[$1]+=$2; r[$1]+=$3; t[$1]+=$4 }
  END { for (u in p) printf "%-14s %7d %9d %11.1f %9.0f\n", u, p[u], t[u], c[u], r[u]/1024 }
' | sort -k4 -rn
echo
echo "NB: CPU% de ps est une moyenne sur la duree de vie du processus, pas l'instantane."
echo "    Croiser avec 'top -b -n2 -d1' ci-dessous pour l'instantane."
echo
echo "-- Instantane top (2e iteration, valeurs fiables) --"
if have top; then top -b -n2 -d1 2>/dev/null | awk '/^top -/{i++} i==2' | head -n $((TOPN+8)); else na "top absent"; fi
echo
echo "-- Principaux consommateurs par utilisateur --"
for u in $(ps -eo user= | sort -u); do
  echo "[$u]"
  ps -u "$u" -o pid,pcpu,pmem,etime,args --sort=-pcpu --no-headers 2>/dev/null | head -5
done

# =========================================================================
step "4. NODE.JS, NPM/PNPM/YARN/BUN, ET MIGRATIONS DE BASES"
# =========================================================================
echo "-- Processus Node.js et gestionnaires de paquets --"
NODEPIDS=$(pgrep -f '(^|/)(node|npm|npx|pnpm|yarn|bun)( |$)' 2>/dev/null | exclude_self)
if [ -z "$NODEPIDS" ]; then
  echo "Aucun processus node/npm/npx/pnpm/yarn/bun."
else
  for pid in $NODEPIDS; do
    [ -d "/proc/$pid" ] || continue
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null)
    read -r ppid user pcpu rss etime < <(ps -o ppid=,user=,pcpu=,rss=,etime= -p "$pid" 2>/dev/null)
    role="INDETERMINE"
    case "$cmd" in
      *migrat*|*prisma*migrate*|*knex*|*sequelize*|*typeorm*|*flyway*|*liquibase*|*alembic*) role="MIGRATION DE BASE" ;;
      *build*|*webpack*|*vite*build*|*tsc*|*esbuild*|*next*build*) role="COMPILATION / BUILD" ;;
      *"npm run"*|*"pnpm run"*|*"yarn run"*) role="TACHE PONCTUELLE (script npm)" ;;
      *server*|*start*|*next*start*|*nest*|*express*) role="SERVEUR APPLICATIF" ;;
    esac
    echo "----------------------------------------------------------------"
    echo "PID $pid  PPID ${ppid:-?} (parent: $(ps -o comm= -p "${ppid:-0}" 2>/dev/null))  user=${user:-?}"
    echo "  CPU=${pcpu:-?}%  RSS=$(( ${rss:-0} /1024 ))Mio  elapsed=${etime:-?}"
    echo "  Cwd (= application) : ${cwd:-INDETERMINE}"
    echo "  Projet             : $( [ -r "$cwd/package.json" ] && grep -m1 '"name"' "$cwd/package.json" 2>/dev/null || echo 'INDETERMINE (pas de package.json lisible)' )"
    echo "  Nature             : $role"
    echo "  Commande           : $cmd"
  done
  echo
  echo "Node concurrents : $(echo "$NODEPIDS" | wc -w) processus."
fi
echo
echo "-- Migrations de bases (tous langages) --"
echo "PIEGE CONNU : les processus nommes 'migration/0', 'migration/1', ... sont des"
echo "              threads NOYAU de migration de taches entre CPU (un par coeur)."
echo "              Ce ne sont PAS des migrations de base de donnees. Ils sont exclus."
MIGPIDS=$(pgrep -f 'migrat|alembic|flyway|liquibase|prisma|knex|sequelize|typeorm|rails db:|artisan migrate|goose|dbmate' 2>/dev/null \
  | exclude_self \
  | while read -r p; do [ -n "$(readlink "/proc/$p/exe" 2>/dev/null)" ] && echo "$p"; done)
if [ -z "$MIGPIDS" ]; then
  echo "Aucun processus de migration detecte par motif de ligne de commande."
  echo "ATTENTION : une migration executee DANS le serveur de base (requete longue) n'apparait"
  echo "            pas ici ; voir la section sessions SQL ci-dessous."
else
  ps -o pid,ppid,user,pcpu,pmem,etime,args -p $(echo "$MIGPIDS" | tr '\n' ',' | sed 's/,$//') 2>/dev/null
fi
echo
echo "-- Serveurs de bases de donnees --"
ps -eo pid,ppid,user,pcpu,pmem,rss,etime,args \
  | grep -Ei '(postgres|mysqld|mariadbd|mongod|redis-server|sqlite)' | grep -v grep || echo "Aucun serveur de base detecte."
echo
echo "-- Requetes actives PostgreSQL (lecture seule) --"
if have psql; then
  sudo -n -u postgres psql -Atc \
    "select pid, usename, state, now()-query_start as duree, left(query,120) from pg_stat_activity where state <> 'idle' order by query_start;" \
    2>/dev/null || na "psql present mais interrogation impossible (droits / serveur absent)"
else
  na "psql absent"
fi
echo
echo "-- Requetes actives MySQL/MariaDB (lecture seule) --"
if have mysqladmin; then
  mysqladmin processlist 2>/dev/null || na "mysqladmin present mais interrogation impossible (droits)"
else
  na "mysqladmin absent"
fi

# =========================================================================
step "6. COMPOSANTS NERONOS"
# =========================================================================
echo "Format : PID | CPU | RAM(Mio) | etat | service | role"
NERON_UNITS="neron neron-core neron-llm neron-stt neron-vocal neron-doctor neron-kula
neron-cognitive-loop neron-cognitive-daemon neron-self-model-loop neron-world-model-loop
neron-homeassistant kula"
for u in $NERON_UNITS; do
  if have systemctl && systemctl list-unit-files "${u}.service" >/dev/null 2>&1 \
     && systemctl cat "${u}.service" >/dev/null 2>&1; then
    act=$(systemctl show -p ActiveState --value "${u}.service" 2>/dev/null)
    sub=$(systemctl show -p SubState --value "${u}.service" 2>/dev/null)
    mpid=$(systemctl show -p MainPID --value "${u}.service" 2>/dev/null)
    if [ "${mpid:-0}" -gt 0 ] 2>/dev/null; then
      read -r pcpu rss < <(ps -o pcpu=,rss= -p "$mpid" 2>/dev/null)
      printf "%-8s | %6s | %8s | %-10s | %-28s | %s\n" \
        "$mpid" "${pcpu:-?}" "$(( ${rss:-0} /1024 ))" "$act/$sub" "${u}.service" "composant NeronOS"
    else
      printf "%-8s | %6s | %8s | %-10s | %-28s | %s\n" "-" "-" "-" "$act/$sub" "${u}.service" "non demarre"
    fi
  fi
done
echo
echo "-- Processus NeronOS hors systemd (Core / LLM / Goal / Memory / Doctor / Watchdog) --"
ps -eo pid,ppid,user,pcpu,pmem,rss,nlwp,stat,etime,args \
  | grep -Ei 'neron|kula|doctor\.sh|watchdog\.sh|goal_system|memory|self_model|world_model' \
  | grep -v grep || echo "Aucun."
echo
echo "-- Tous les processus de l'utilisateur neron --"
if id neron >/dev/null 2>&1; then
  ps -u neron -o pid,ppid,pcpu,pmem,rss,nlwp,stat,etime,args --no-headers 2>/dev/null || echo "Aucun."
  echo "Total CPU/RAM utilisateur neron :"
  ps -u neron -o pcpu=,rss= 2>/dev/null | awk '{c+=$1;r+=$2} END{printf "  CPU cumule %.1f%%  RSS cumule %.0f Mio  (%d procs)\n", c, r/1024, NR}'
else
  na "utilisateur 'neron' inexistant sur cette machine"
fi

# =========================================================================
step "7. OLLAMA (lecture seule - aucune modification)"
# =========================================================================
echo "-- Processus --"
ps -eo pid,ppid,user,pcpu,pmem,rss,nlwp,stat,etime,args | grep -i ollama | grep -v grep \
  || echo "Aucun processus Ollama."
echo
echo "-- Enfants du serveur Ollama (runners de modele) --"
OPID=$(pgrep -x ollama 2>/dev/null | head -1)
if [ -n "$OPID" ]; then
  ps --ppid "$OPID" -o pid,pcpu,pmem,rss,etime,args --no-headers 2>/dev/null || echo "Aucun enfant."
else
  echo "Serveur Ollama non trouve."
fi
echo
echo "-- Modeles actuellement charges en memoire --"
if have ollama; then
  ollama ps 2>/dev/null || na "'ollama ps' a echoue (service arrete ?)"
else
  na "binaire ollama absent"
fi
echo
echo "-- Etat systemd --"
if have systemctl; then
  systemctl is-active ollama.service 2>/dev/null
  systemctl show ollama.service -p ActiveState -p SubState -p MainPID \
    -p NRestarts -p ActiveEnterTimestamp -p FragmentPath -p DropInPaths 2>/dev/null \
    || na "unite ollama.service inconnue"
else
  na "systemctl absent"
fi
echo
echo "-- GPU --"
if have nvidia-smi; then nvidia-smi; elif have rocm-smi; then rocm-smi; else na "aucun outil GPU (nvidia-smi/rocm-smi) - GPU probablement absent, inference CPU"; fi
echo
echo "CONCLUSION OLLAMA : si 'ollama ps' est vide ET qu'aucun processus enfant runner"
echo "n'existe ET que le CPU du serveur est proche de 0, Ollama ne peut pas expliquer"
echo "la charge : le serveur au repos ne consomme quasiment rien."

# =========================================================================
step "8. WARNING SYSTEMD SUR ollama.service (diagnostic, AUCUNE correction)"
# =========================================================================
if have systemctl; then
  FRAG=$(systemctl show ollama.service -p FragmentPath --value 2>/dev/null)
  DROP=$(systemctl show ollama.service -p DropInPaths --value 2>/dev/null)
  echo "FragmentPath : ${FRAG:-INDETERMINE}"
  echo "DropInPaths  : ${DROP:-aucun}"
  echo
  echo "-- Dates de modification des fichiers concernes --"
  for f in $FRAG $DROP; do [ -e "$f" ] && stat -c '%y  %n' "$f"; done
  echo
  echo "-- Date du dernier rechargement de la configuration systemd --"
  systemctl show -p FinishTimestamp --value 2>/dev/null
  stat -c '%y  %n' /run/systemd/generator 2>/dev/null || echo "(generateurs non disponibles)"
  echo
  echo "-- L'unite est-elle marquee comme necessitant un daemon-reload ? --"
  systemctl show ollama.service -p NeedDaemonReload --value 2>/dev/null
  echo
  echo "-- Journal de l'unite (20 dernieres lignes) --"
  journalctl -u ollama.service -n 20 --no-pager 2>/dev/null || na "journalctl indisponible"
  echo
  echo "INTERPRETATION :"
  echo " - 'NeedDaemonReload=no' + fichiers unit vieux de plusieurs mois"
  echo "   => le warning est HISTORIQUE et SANS RAPPORT avec la charge actuelle."
  echo " - Un warning 'changed on disk' n'a de toute facon aucun cout CPU :"
  echo "   il signale seulement que systemd n'a pas relu le fichier."
  echo " - AUCUNE correction n'est appliquee ici (pas de daemon-reload)."
else
  na "systemctl absent - warning non analysable"
fi

# =========================================================================
step "10. SYNTHESE : TABLEAU RECAPITULATIF"
# =========================================================================
printf "%-7s %-10s %6s %8s %-18s %-16s %-22s %-9s %s\n" \
  "PID" "USER" "CPU%" "RAM_Mio" "PROCESSUS" "PARENT" "ORIGINE" "NERONOS?" "IMPACT"
ps -eo pid=,user=,pcpu=,rss=,comm=,ppid= --sort=-pcpu | head -n "$TOPN" | \
while read -r pid user pcpu rss comm ppid; do
  parent=$(ps -o comm= -p "${ppid:-0}" 2>/dev/null)
  exe=$(readlink "/proc/$pid/exe" 2>/dev/null)
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  unit="-"
  [ -r "/proc/$pid/cgroup" ] && unit=$(grep -o '[^/]*\.service' "/proc/$pid/cgroup" 2>/dev/null | head -1)
  cat_=$(classify "$pid" "$exe" "${unit:--}" "$user" "$cmd")
  case "$cat_" in NERONOS*) isn="OUI" ;; *) isn="NON" ;; esac
  cpu_i=${pcpu%%.*}
  if [ "${cpu_i:-0}" -ge 50 ] 2>/dev/null; then imp="MAJEUR"
  elif [ "${cpu_i:-0}" -ge 10 ] 2>/dev/null; then imp="MODERE"
  else imp="faible"; fi
  printf "%-7s %-10s %6s %8s %-18s %-16s %-22s %-9s %s\n" \
    "$pid" "$user" "$pcpu" "$((rss/1024))" "$comm" "${parent:-?}" "${exe:-${unit:--}}" "$isn" "$imp"
done

# =========================================================================
step "VERDICT DE CONTENTION"
# =========================================================================
L1=$(awk '{print $1}' /proc/loadavg)
RATIO=$(awk -v l="$L1" -v n="$NCPU" 'BEGIN{printf "%.2f", l/n}')
WA=$(have vmstat && vmstat 1 2 | tail -1 | awk '{print $16}' || echo "?")
ST=$(have vmstat && vmstat 1 2 | tail -1 | awk '{print $17}' || echo "?")
PSICPU=$(awk '/^some/{print $2}' /proc/pressure/cpu 2>/dev/null | cut -d= -f2)
PSIIO=$(awk '/^full/{print $2}' /proc/pressure/io 2>/dev/null | cut -d= -f2)
PSIMEM=$(awk '/^full/{print $2}' /proc/pressure/memory 2>/dev/null | cut -d= -f2)

echo "Charge par CPU        : $RATIO   (>1.00 = sursouscription)"
echo "iowait                : ${WA}%   (>10% = contention disque)"
echo "steal                 : ${ST}%   (>5% = CPU vole par l'hyperviseur)"
echo "PSI cpu    some avg10 : ${PSICPU:-INDETERMINE}"
echo "PSI io     full avg10 : ${PSIIO:-INDETERMINE}"
echo "PSI memory full avg10 : ${PSIMEM:-INDETERMINE}"
echo
echo "-- Nature dominante de la contention --"
awk -v r="$RATIO" -v wa="${WA:-0}" -v st="${ST:-0}" -v pm="${PSIMEM:-0}" 'BEGIN{
  if (r < 0.7) { print "  Aucune contention significative."; exit }
  if (wa+0 > 10) print "  DOMINANTE I/O : les processus attendent le disque, pas le CPU.";
  if (st+0 > 5)  print "  DOMINANTE STEAL : l hyperviseur prive la VM de CPU.";
  if (pm+0 > 1)  print "  CONTENTION MEMOIRE : recuperation/swap actifs.";
  if (wa+0 <= 10 && st+0 <= 5 && pm+0 <= 1) print "  DOMINANTE CPU : cycles reellement consommes par des processus.";
}'
echo
echo "-- Contribution NeronOS --"
if id neron >/dev/null 2>&1; then
  ps -u neron -o pcpu=,rss= 2>/dev/null | awk -v n="$NCPU" '{c+=$1;r+=$2} END{
    printf "  utilisateur neron : %.1f%% CPU cumule (%.1f%% d un CPU unique en moyenne), %.0f Mio RSS, %d procs\n", c, c, r/1024, NR}'
else
  echo "  utilisateur 'neron' inexistant."
fi
echo
echo "-- Contribution Ollama --"
if pgrep -x ollama >/dev/null 2>&1; then
  ps -o pid=,pcpu=,rss= -p "$(pgrep -x ollama | head -1)" | awk '{printf "  serveur ollama PID %s : %s%% CPU, %.0f Mio RSS\n", $1, $2, $3/1024}'
  echo "  modeles charges : $(have ollama && ollama ps 2>/dev/null | tail -n +2 | wc -l || echo INDETERMINE)"
else
  echo "  Aucun processus Ollama en cours."
fi
echo
echo "-- Conditions pour relancer le benchmark LLM --"
echo "  [ ] charge par CPU < 0.50 sur 5 min      (actuel : $RATIO)"
echo "  [ ] iowait < 5%                          (actuel : ${WA}%)"
echo "  [ ] steal < 2%                           (actuel : ${ST}%)"
echo "  [ ] PSI memory full = 0 et swap inactif"
echo "  [ ] aucune migration de base en cours"
echo "  [ ] aucun build/serveur Node.js etranger au-dessus de 10% CPU"
echo "  [ ] RAM disponible >= taille du modele + 20%"
echo "  Tant qu'une case reste vide, les mesures de latence LLM ne sont pas comparables."
echo
echo "Rapport termine. Aucun processus arrete, aucun service redemarre, aucune configuration modifiee."

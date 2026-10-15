#!/usr/bin/env bash

set -u

NERON_DIR="/srv/Neron/neronOS/neronCore"
LOG_FILE="$HOME/core.log"
PORT=8010

cd "$NERON_DIR" || exit 1

is_running() {
    fuser "${PORT}/tcp" >/dev/null 2>&1
}

start_core() {
    if is_running; then
        echo "Néron Core est déjà démarré."
        return 0
    fi

    [[ -x .venv/bin/python ]] || {
        echo "ERREUR : environnement Python introuvable."
        return 1
    }

    [[ -f secrets.env ]] || {
        echo "ERREUR : secrets.env introuvable."
        return 1
    }

    set -a
    . ./secrets.env
    set +a

    export NERON_ROOT="$NERON_DIR"
    export NERON_CONFIG="$NERON_DIR/neron.yaml"
    export PYTHONPATH="$NERON_DIR:$NERON_DIR/server${PYTHONPATH:+:$PYTHONPATH}"

    echo "Démarrage de Néron Core..."

    nohup ./.venv/bin/python -m common.serve core \
        >> "$LOG_FILE" 2>&1 </dev/null &

    for i in $(seq 1 10); do
        sleep 1
        if is_running; then
            echo "Néron Core démarré avec succès."
            tail -n 8 "$LOG_FILE"
            return 0
        fi
    done

    echo "ERREUR : Néron Core n'a pas démarré."
    tail -n 20 "$LOG_FILE"
    return 1
}

stop_core() {
    if ! is_running; then
        echo "Néron Core est déjà arrêté."
        return 0
    fi

    echo "Arrêt de Néron Core..."
    fuser -k "${PORT}/tcp" || return 1

    for i in $(seq 1 10); do
        sleep 1
        if ! is_running; then
            echo "Néron Core arrêté."
            return 0
        fi
    done

    echo "ERREUR : le port ${PORT} est toujours utilisé."
    return 1
}

case "${1:-}" in
    start)
        start_core
        ;;
    stop)
        stop_core
        ;;
    restart)
        stop_core && sleep 1 && start_core
        ;;
    "")
        if is_running; then
            echo "Néron Core est déjà actif."
            read -r -p "Voulez-vous le redémarrer ? (o/N) : " choix
            case "$choix" in
                o|O|oui|Oui|OUI)
                    stop_core && sleep 1 && start_core
                    ;;
                *)
                    echo "Néron Core reste actif."
                    ;;
            esac
        else
            start_core
        fi
        ;;
    *)
        echo "Utilisation : $0 [start|stop|restart]"
        exit 2
        ;;
esac


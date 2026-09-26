# system/scripts — scripts d'exploitation

Référence d'architecture : [../docs/architecture/neronos-architecture.md](../docs/architecture/neronos-architecture.md)

La racine est `/etc/neronOS`. Aucun script ne doit référencer `/etc/neron` ni
`/srv/homelab/server-1/neronOS` : `tests/test_runtime_paths.py` le vérifie.

## Déployés sur le système

| Script | Installé comme | Appelé par |
|---|---|---|
| `neron.sh` | `/usr/local/bin/neron` | l'humain (CLI principale) |
| `doctor_diagnose.sh` | — | `neron-doctor-diagnose.timer`, toutes les 5 min |

`system/deploy/install.sh` gère l'installation ; `install.sh check` compare le
dépôt au système.

## Exploitation courante

| Script | Rôle |
|---|---|
| `neron-boot.sh` | séquence de démarrage ordonnée de la pile |
| `server.sh`, `client.sh` | pilotage des services serveur / client |
| `backup.sh` | sauvegarde |
| `neron-registry` | wrapper sur `python -m server.common.cli` |
| `purge_secrets.sh` | purge des secrets d'un checkout |

## Installation et dépendances

| Script | Rôle |
|---|---|
| `install.sh` | installation complète depuis zéro |
| `install_deps.py`, `kdeps.py` | vérification des dépendances Python |
| `ollama.sh` | installation et pilotage d'Ollama |
| `ha.sh`, `ha_install.sh` | Home Assistant |

## Outillage

| Script | Rôle |
|---|---|
| `llmfit/llmfit.py` | dimensionnement des modèles par rapport au matériel |
| `send_telegram_report.py` | rapport cognitif vers Telegram |
| `telegram.sh` | configuration Telegram |
| `test_yaml.py` | validation syntaxique de `neron.yaml` |
| `kdeps/` | tests des vérificateurs de dépendances (exclus de pytest) |
| `setup_google_gateway.sh` | wizard : connecte le connecteur Google de `server/gateways` (OAuth device flow) |

## Note

`neron-fix.sh`, `run-distributed.sh`, `start.py`, `stop.py`, `bootstrap.sh`,
`grep.sh` et `purge_pyc.sh` ont été supprimés en Phase 1 : ils pilotaient
uvicorn ou tmux à la main sous l'ancienne racine `/etc/neron`, remplacés par le
template `neron@.service` et `common.serve`. Leur contenu reste dans l'historique
Git.

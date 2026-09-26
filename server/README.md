# server/ — backend de NéronOS

Référence d'architecture : [system/docs/architecture/neronos-architecture.md](../system/docs/architecture/neronos-architecture.md)

## Contenu

Sous-modules Git (un dépôt chacun) :

| Répertoire | Bloc | Rôle |
|---|---|---|
| `core/` | Core | orchestration, API publique, registry, SelfModel canonique |
| `llm/` | Cœur | routage des tâches vers les providers de génération |
| `memory/` | Cœur | Oblivia — mémoire et source de vérité des connaissances |
| `goal/` | Architecte | objectifs, plans, projets, exécution |
| `doctor/` | Architecte | diagnostic et autocorrection |
| `watchdog/` | Architecte | surveillance — **vide à ce jour (v0.0.0)** |
| `voice/`, `print/`, `gateways/` | Capabilities | services externes |

Code porté par le dépôt parent :

| Répertoire | Statut |
|---|---|
| `common/` | socle partagé — légitimement dans le parent |
| `modules/`, `agents/`, `tools/` | logique métier à répartir vers les sous-modules (Phase 2) |
| `integrations/` | connecteur Home Assistant — relève de Capabilities |

## Initialisation

```bash
cd /etc/neronOS
git submodule update --init --recursive
```

## Démarrage

Tous les services métier passent par un template systemd unique. L'adresse et
le port viennent de `neron.server.yaml` (section `nodes`), jamais de l'unité :

```bash
sudo systemctl start neron@core.service      # ou llm, memory, goal, doctor…
sudo systemctl start neron.target            # toute la pile
```

Ce que fait l'unité, pour un nœud `<n>` :

```text
/etc/neronOS/venv/bin/python -m common.serve <n>
```

`common.serve` lit `nodes.<n>`, pose `NERON_SERVICE_HOST` / `NERON_SERVICE_PORT`
/ `NERON_CORE_URL` / `NERON_LLM_URL` dans l'environnement, importe `<n>.app:app`
et lance uvicorn.

## Vérification

```bash
make health                        # environnement + état de tous les services
./system/deploy/install.sh check   # dépôt vs configuration déployée
curl -s http://127.0.1.1:8010/health
```

## Chemins et environnement

La racine est `/etc/neronOS`. Les chemins runtime sont centralisés dans
`common/paths.py` et surchargeables par variable d'environnement :

| Variable | Défaut |
|---|---|
| `NERON_ROOT` | `/etc/neronOS` |
| `NERON_CONFIG` | `$NERON_ROOT/neron.yaml` |
| `NERON_DATA_DIR` | `$NERON_ROOT/data` |
| `NERON_SERVER_DIR` | `$NERON_ROOT/server` |
| `NERON_WORKSPACE_DIR` | `$NERON_ROOT/workspace` |
| `NERON_SECRETS_FILE` | `$NERON_ROOT/secrets.env` |

L'environnement commun des unités vit dans `env/common.env` (versionné sous
`system/deploy/env/common.env`). Les secrets vivent dans `secrets.env`, non
versionné, mode `0640`.

## Configuration

| Fichier | Contenu |
|---|---|
| `neron.yaml` | comportement : tâches LLM, agents, scheduler, doctor, CORS |
| `neron.server.yaml` | topologie : `cluster` et `nodes` — source de vérité |
| `secrets.env` | secrets uniquement, jamais versionné |

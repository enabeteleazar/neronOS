# SelfModel canonique

Voir aussi : [Architecture de référence](neronos-architecture.md).

## Audit

Le SelfModel actif est `server/core/modules/self_model/service.py`. Il consolide
l'identité, l'état opérationnel et les événements récents sans devenir un
collecteur système autonome.

Le parent ne fournit que des pilotes autour de ce service canonique, dans
`server/modules/self_model/` : `subscriber.py`, `monitor.py`.
(`self_model_loop.py` a été supprimé en Phase 2B, voir ci-dessous.) Tous appellent `core.modules.self_model.get_self_model()`.

Les façades de compatibilité `server/core/self_model/self_model.py` et
`server/modules/self_model/self_model.py` qui étaient citées ici **n'existent
plus**. Ne pas les recréer : le point d'entrée est
`from core.modules.self_model import get_self_model`.

## Écrivain unique — appliqué en Phase 2B

**Core est l'unique écrivain du SelfModel.**

`neron-self-model-loop.service` a été **arrêtée, désactivée et supprimée** (unité
et module `modules/self_model/self_model_loop.py`). Elle appelait `refresh()` +
`save_state()` toutes les 5 secondes depuis un processus distinct, en concurrence
non verrouillée avec les écritures de Core.

Ce qui a changé dans `core/modules/self_model/service.py` :

| | Avant | Après |
|---|---|---|
| État mutable (`last_intent`, `last_agent`, `recent_activity`…) | lu/écrit dans le fichier à **chaque** mutation | gardé **en mémoire** (`_mutable`) |
| Coût d'une requête sur le chemin `agent_router` | **7** cycles lecture-modification-écriture d'un fichier de ~50 Ko | **0** écriture |
| Persistance | boucle dédiée, toutes les 5 s | `refresh()`, **bridée à 30 s** (`PERSIST_INTERVAL_SECONDS`) |
| Écrivains simultanés | 2 processus, sans verrou | **1** (Core) |

Le fichier `data/self_model_state.json` est désormais un **cache de redémarrage** :
il amorce `_mutable` au démarrage et n'est plus un canal de synchronisation entre
processus. `save_state(force=True)` permet une écriture immédiate.

Rien n'a été perdu : Core appelle déjà `refresh()` à la lecture
(`self_model_routes.py`, `cognitive_core_routes.py`), et `SelfMonitor` tourne dans
Core. La boucle ne faisait que dupliquer ce travail — en relançant toutes les 5 s
des sondes HTTP vers tous les services et deux appels `systemctl`, sur une machine
à 2 cœurs.

## Sources de vérité

Le SelfModel agrège en lecture :

- Identity pour l'identité ;
- Status pour les ressources et l'état opérationnel ;
- Service Registry pour les services actifs connus ;
- Provider Registry pour les providers et leurs capacités ;
- A2A Client et Agent Registry pour les agents ;
- Memory Provider pour la disponibilité mémoire ;
- Goal Engine et le runtime Goal pour les objectifs.

Il n'appelle directement ni `systemctl`, ni SQLite, ni Obsidian, ni Ollama.

`pc_remote_agent` est un agent A2A et apparaît exclusivement dans
`/selfmodel/agents`. Il ne fait pas partie du Provider Registry. Les providers
actuels exposés par `/selfmodel/providers` sont `oblivia` et `llm`.

Chaque entrée topologique expose :

- `kind` : `provider` ou `agent` ;
- `runtime_type` : `persistent`, `temporary` ou `unknown` ;
- `managed_by` : registre ou moteur responsable.

Les providers sont persistants et gérés par `provider_registry`. Les agents
peuvent être permanents ou temporaires et être gérés par `agent_registry`,
`a2a` ou `goal`.

La règle d'architecture est stricte :

- Goal Engine développe les agents et modules nécessaires ;
- un futur Provider Agent gérera leur présence et leur exécution ;
- les Providers actuels exposent uniquement des capacités stables.

Le Provider Agent est seulement documenté ici : il n'est pas créé dans cette
phase.

## Utilisation par Goal Engine

Avant l'analyse d'un objectif, Goal Engine charge un contexte SelfModel en
lecture : état, capacités, providers, agents, mémoire et architecture. Il
privilégie l'agent ou le provider déclaré dans cette vue. Si le SelfModel est
indisponible ou périmé, un fallback local contrôlé reste disponible et son
utilisation est signalée dans les diagnostics du goal.

Les résultats Goal exposent :

- `selfmodel_used`
- `selfmodel_available`
- `selfmodel_error`
- `selected_provider_from_selfmodel`
- `selected_agent_from_selfmodel`
- `selfmodel_decision_reason`

## API

Toutes les routes sont protégées par l'authentification centralisée :

> **Corrigé en Phase 2B.** Ce document annonçait des routes `/selfmodel/*` et
> présentait `/self-model/*` comme d'anciennes routes de compatibilité. C'est
> l'inverse : vérification faite sur l'OpenAPI du Core en production, **seules les
> routes `/self-model/*` existent**. `/selfmodel/status` renvoie 404.

- `GET /self-model`
- `GET /self-model/status`
- `GET /self-model/summary`
- `GET /self-model/identity`
- `GET /self-model/capabilities`
- `GET /self-model/providers`
- `GET /self-model/services`
- `GET /self-model/agents`
- `GET /self-model/agents/{agent_id}/status`
- `GET /self-model/memory`
- `GET /self-model/goals`
- `GET /self-model/architecture`
- `GET /self-model/context`
- `GET /self-model/homelab/slots/{unit_id}`

C'est le **transport de l'Architecte** : Goal, Doctor et Watchdog lisent le
SelfModel par HTTP, jamais en ouvrant le fichier de cache.

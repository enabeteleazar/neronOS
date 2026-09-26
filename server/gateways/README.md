# gateways — passerelles vers services externes

Service HTTP (`neron@gateways`) qui centralise l'acces de Néron aux services
externes (Google, Microsoft/Outlook, Apple, GitHub, Notion...) pour les
domaines mail, contacts, notes, reminders, calendar, repos, docs.

Remplace l'ancienne approche « un module dédié par service externe »
(reminders, calendars) par un registre déclaratif de connecteurs.

## Contenu

| Fichier | Rôle |
|---|---|
| `connectors.yaml` | registre déclaratif : id, domaines couverts, protocole, type d'auth, variables `secrets.env` attendues |
| `registry.py` | charge `connectors.yaml`, expose la recherche par domaine/id |
| `store.py` | état de connexion par connecteur (sqlite, jamais de secret) |
| `models.py` | schémas Pydantic partagés par l'API |
| `auth.py` | dépendance FastAPI d'authentification par clé API (fail-closed) |
| `config.py` | lecture de la section `gateways:` de `neron.yaml` |
| `app.py` | API FastAPI |

## API

- `GET /gateways` — liste tous les connecteurs + leur état
- `GET /gateways/domain/{domain}` — connecteurs couvrant ce domaine (liste vide = aucune passerelle)
- `GET /gateways/{id}` — un connecteur + son état
- `POST /gateways/{id}/connect` — vérifie que les variables `credential_env` sont présentes dans l'environnement, marque `connected` sinon renvoie 409 avec les variables manquantes et `connect_hint`. **Renvoie 409 pour `google`** : voir le flux OAuth device ci-dessous.
- `POST /gateways/{id}/disconnect` — repasse le connecteur à `configured_disconnected` et efface le refresh token stocké s'il y en a un.
- `POST /gateways/google/oauth/start` — démarre le flux OAuth "device authorization grant" : renvoie `user_code` + `verification_url` (l'utilisateur les saisit sur `google.com/device`, sur n'importe quel appareil).
- `POST /gateways/google/oauth/poll` — à rappeler périodiquement (toutes les `interval` secondes renvoyées par `/oauth/start`) jusqu'à `status: "connected"` (ou `"pending"` en attendant, ou 409/502 en cas d'erreur).

Toutes les routes exigent l'en-tête `X-Gateways-Key` (voir `NERON_GATEWAYS_API_KEY` dans `secrets.env`).

## Configurer Google

`system/scripts/setup_google_gateway.sh` guide pas à pas : création du
projet Google Cloud, activation de l'API Calendar, écran de consentement
OAuth, identifiant OAuth de type "TVs and Limited Input devices", puis lance
et termine le flux `/gateways/google/oauth/start` + `/oauth/poll`
automatiquement. Nécessite `curl` et `jq`.

## Portée actuelle

- **Google** : flux OAuth réel implémenté (device authorization grant, RFC 8628) — voir `providers/google_auth.py`. Une seule action réelle branchée : lister les prochains événements Google Agenda (`providers/google_calendar.py` + `actions.py`), utilisée automatiquement par `CapabilityResolver` quand le domaine `calendar` est demandé et Google est connecté. Mail/contacts/notes/reminders via Google restent à brancher — même pattern, un nouveau `providers/google_*.py` + une entrée dans `resolver._execute_gateway`.
- **Microsoft, Apple, GitHub, Notion** : `connect` vérifie seulement la présence d'identifiants statiques dans `secrets.env` (pas d'échange OAuth réel), et `use_gateway` renvoie un message honnête indiquant que l'exécution réelle n'est pas encore branchée. C'est une extension prévue, pas un changement d'API.

Les refresh tokens obtenus par OAuth sont stockés à part (`token_store.py`,
fichier sqlite dédié en mode 0600, jamais dans `secrets.env` ni dans
`store.ConnectionStore` qui documente explicitement ne jamais porter de
secret).

## Intégration Core

`server/modules/capabilities/decision_engine.py` consulte ce registre (en
process, lecture directe de `registry.py`/`store.py` — pas d'appel HTTP,
même logique que les dépendances `goal`/`agents`/`tools` du resolver) pour
les domaines `mail`, `contacts`, `notes`, `reminders`, `calendar`, `repos`,
`docs` : avant de générer un agent ou un tool pour une demande ponctuelle
sur l'un de ces domaines, il regarde si un connecteur le couvre.

- Connecteur connecté → la demande est routée vers ce connecteur (l'appel
  réel à l'API du connecteur reste à implémenter, cf. section précédente).
- Connecteur couvrant le domaine mais pas connecté → Néron propose de se
  connecter (`connect_hint`).
- Aucun connecteur pour ce domaine → Néron l'indique explicitement, sans
  tenter de générer un agent de remplacement.

Une demande *durable* (« surveille mes mails ») n'est pas interceptée : elle
continue vers le Goal Engine, ce comportement est hors de la portée de cette
itération.

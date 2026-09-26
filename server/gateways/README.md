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
- `POST /gateways/{id}/connect` — vérifie que les variables `credential_env` sont présentes dans l'environnement, marque `connected` sinon renvoie 409 avec les variables manquantes et `connect_hint`
- `POST /gateways/{id}/disconnect` — repasse le connecteur à `configured_disconnected`

Toutes les routes exigent l'en-tête `X-Gateways-Key` (voir `NERON_GATEWAYS_API_KEY` dans `secrets.env`).

## Portée actuelle

Ce service ne fait pas (encore) l'échange OAuth réel : `connect` vérifie la
présence des identifiants dans `secrets.env` et bascule l'état. L'obtention
de ces identifiants (flux OAuth2, mot de passe d'application) reste un pas
manuel documenté par `connect_hint`. C'est une extension prévue, pas un
changement d'API.

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

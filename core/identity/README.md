Voici un README.md adapté à l’état actuel du module core/identity.

À placer dans :

/etc/neronOS/server/core/identity/README.md
# Néron Identity
## Présentation
Le module `identity` est le système d'identité central de Néron.
Il définit qui est Néron, son rôle, sa personnalité, son style conversationnel et son contexte système.
L'identité appartient au Core de NéronOS.
Le LLM n'est pas Néron.
Le LLM est uniquement un moteur de génération de réponses utilisant l'identité fournie par le Core.
---
# Architecture

identity/

├── loader.py
├── schema.py
├── validator.py
├── init.py
│
└── documents/
├── NERON.md
├── PERSONALITY.md
├── CONVERSATION.md
└── CONTEXT.md

---
# Rôle des composants
## loader.py
Responsable du chargement de l'identité.
Fonctions principales :
- lecture des documents d'identité ;
- construction de l'objet `NeronIdentity` ;
- génération du prompt système ;
- compatibilité avec les services Core existants.
Interfaces publiques :
```python
get_identity()

Retourne l’identité structurée de Néron.

build_identity_prompt()

Construit le prompt système envoyé au LLM.

⸻

schema.py

Définit la structure interne d’une identité Néron.

Objet principal :

NeronIdentity

Contient :

* nom ;
* version ;
* rôle ;
* mission ;
* identité ;
* personnalité ;
* conversation ;
* contexte.

⸻

validator.py

Vérifie que l’identité chargée est valide.

Contrôles actuels :

* présence des champs obligatoires ;
* cohérence minimale de la structure.

Une identité invalide empêche le chargement.

⸻

Documents d’identité

NERON.md

Identité fondamentale.

Contient :

* nom ;
* version ;
* rôle ;
* mission ;
* définition du système.

Exemple :

Néron est un assistant personnel IA local.
Le LLM est un composant interchangeable.
L'identité appartient au Core.

⸻

PERSONALITY.md

Définit le comportement de Néron.

Contient :

* traits ;
* valeurs ;
* manière de raisonner ;
* règles de communication.

Objectif :

Créer une personnalité stable indépendamment du modèle LLM utilisé.

⸻

CONVERSATION.md

Définit le style d’interaction.

Contient :

* manière de répondre ;
* gestion du contexte ;
* continuité conversationnelle ;
* adaptation utilisateur.

⸻

CONTEXT.md

Contient le contexte système stable.

Exemples :

* architecture NéronOS ;
* services disponibles ;
* informations générales nécessaires au fonctionnement.

La mémoire utilisateur dynamique n’est pas stockée ici.

⸻

Flux de fonctionnement

Utilisateur
    |
    v
Core Gateway
    |
    v
build_identity_prompt()
    |
    v
Identity Loader
    |
    +--> NERON.md
    +--> PERSONALITY.md
    +--> CONVERSATION.md
    +--> CONTEXT.md
    |
    v
Prompt système complet
    |
    v
LLM
    |
    v
Réponse de Néron

⸻

Compatibilité Core

Le module conserve les anciennes interfaces :

from core.identity import get_identity

et :

from core.identity import build_identity_prompt

Services utilisant l’identité :

* Core Gateway ;
* Telegram Gateway ;
* Self Model ;
* Configuration Core.

⸻

Validation MVP

Version actuelle :

Identity MVP v1

Validations :

✅ Chargement des documents
✅ Construction identité runtime
✅ Validation des champs
✅ Génération prompt système
✅ Compatibilité Core existant

⸻

Évolutions prévues

Identity Runtime

Créer une identité chargée en mémoire au démarrage du Core.

Objectifs :

* éviter les lectures disque répétées ;
* permettre un état identité runtime ;
* préparer l’évolution autonome.

⸻

Identity Versioning

Ajouter un système de version d’identité.

Exemple :

Identity v1.0
Identity v1.1
Identity v2.0

⸻

Identity Tests

Créer des tests comportementaux :

Exemples :

Qui es-tu ?
Quel est ton rôle ?
Quel est ton objectif ?

Vérifier que les réponses restent cohérentes.

⸻

Principe fondamental

Néron n’est pas son modèle de langage.

Le modèle LLM est remplaçable.

L’identité, la personnalité et les règles comportementales appartiennent au Core NéronOS.

Ce README documente le MVP validé et prépare les prochaines évolutions sans sur-concevoir le système.

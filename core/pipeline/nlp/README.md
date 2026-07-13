# French Text Normalizer

Le normalizer français est le point d'entrée commun pour rendre les requêtes
utilisateur moins dépendantes des formulations exactes avant routage.

Flux cible:

1. texte brut depuis API, Telegram, Voice Interface, Mobile ou STT
2. `core.pipeline.nlp.french_normalizer.normalize_text`
3. `IntentRouter` et détecteurs locaux
4. `CoreOrchestrator`

Il applique des règles linguistiques légères et extensibles:

- minuscules et espaces multiples
- normalisation Unicode
- suppression des accents pour le matching
- nettoyage de ponctuation non utile
- apostrophes et tirets transformés en tokens comparables
- corrections grammaticales fréquentes: `qui est tu` -> `qui es tu`,
  `tu est` -> `tu es`, `quel heure` -> `quelle heure`
- petites variantes orales et STT: suppression de fillers (`euh`, `heu`)

Pour ajouter une règle, créer une fonction `list[str] -> list[str]`, l'ajouter
dans `FrenchTextNormalizer.rules`, puis couvrir le cas par un test. Les règles
doivent rester génériques: préférer une transformation grammaticale ou orale à
une liste de phrases complètes.

Evolution possible: remplacer ou compléter ces règles par un modèle NLP/LLM
local de réécriture canonique, tout en conservant l'API `normalize_text`.

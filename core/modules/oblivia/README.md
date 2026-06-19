# Oblivia

Chef de mémoire officiel de Néron.

## Architecture

Néron
↓
Oblivia
├── SQLite (mémoire nerveuse)
└── Obsidian (mémoire autobiographique)

## Rôles

SQLite :
- runtime
- agents
- goals
- événements
- historique

Obsidian :
- identité
- décisions
- roadmap
- journal
- leçons apprises

## Objectif

Fournir un point d'accès unique à la mémoire de Néron.

## Normalisation de recherche

Oblivia normalise les requêtes et les textes indexés avant comparaison :
- minuscules ;
- Unicode normalisé ;
- accents supprimés ;
- espaces multiples réduits.

Les contenus originaux restent conservés et renvoyés avec leurs accents. La
normalisation ne sert qu'à la recherche, afin que les variantes saisies par
l'utilisateur retrouvent les mêmes souvenirs.

Exemple :
- `mémoire de Néron`
- `memoire de Neron`
- `MEMOIRE DE NERON`

Ces requêtes ciblent toutes la forme normalisée `memoire de neron` et doivent
retrouver les mêmes entrées SQLite, Obsidian et sémantiques.

## Évolution future

- MCP Memory Server
- recherche sémantique
- résumés automatiques
- mémoire long terme

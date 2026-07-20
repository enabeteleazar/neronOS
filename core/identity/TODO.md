# Néron Identity TODO

## MVP actuel - Identity v1

Status: ✅ Validé

- [x] Création du système identity dédié au Core
- [x] Séparation identité / personnalité / conversation / contexte
- [x] Création du Identity Loader
- [x] Création du schéma NeronIdentity
- [x] Création du validator
- [x] Compatibilité avec les appels Core existants
- [x] Génération du prompt système complet
- [x] Documentation README

---

# Améliorations prévues

## Identity Runtime

- [ ] Charger l'identité une seule fois au démarrage du Core
- [ ] Ajouter un cache mémoire Identity Runtime
- [ ] Permettre le rechargement contrôlé de l'identité
- [ ] Ajouter un état runtime de l'identité

---

## Identity Versioning

- [ ] Ajouter une version dédiée de l'identité
- [ ] Détecter les changements de documents
- [ ] Historiser les évolutions d'identité
- [ ] Ajouter une migration des anciennes versions

---

## Validation avancée

- [ ] Vérifier la cohérence entre les documents
- [ ] Détecter les contradictions d'identité
- [ ] Ajouter des règles de validation comportementales
- [ ] Ajouter un rapport de validation au démarrage du Core

---

## Identity Tests

- [ ] Créer des tests automatiques d'identité
- [ ] Vérifier les réponses à des questions fondamentales :
  - Qui es-tu ?
  - Quel est ton rôle ?
  - Quelle est ta mission ?
  - Quel est ton environnement ?
- [ ] Vérifier la stabilité du comportement entre différents LLM

---

## Memory Integration

- [ ] Séparer clairement identité statique et mémoire utilisateur
- [ ] Injecter le contexte utilisateur via Memory
- [ ] Ajouter un contexte conversationnel dynamique
- [ ] Éviter de charger des informations temporaires dans identity

---

## Évolution comportementale

- [ ] Définir précisément les valeurs de Néron
- [ ] Définir les règles de communication avancées
- [ ] Ajouter une politique de raisonnement
- [ ] Ajouter une politique de transparence et limites

---

# Architecture cible

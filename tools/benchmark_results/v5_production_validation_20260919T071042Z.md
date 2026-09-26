# V5 — Validation production contrôlée : qwen2.5:1.5b + num_predict=96

## 1. Résumé exécutif

Test réel effectué directement sur `neron@llm.service` en production (pas d'instance jetable). Configuration candidate activée pendant ~35 minutes, testée avec 84 appels réels, puis **restauration complète et vérifiée** de la configuration d'origine.

**Résultat principal** : la candidate **corrige exactement le défaut qui a motivé toute cette investigation** (timeouts sur génération non plafonnée — 3/54 échecs en baseline, 0/84 en candidate) et **divise par deux le P95 de latence** (56 616 ms → 28 092 ms sur le même jeu de prompts). Mais elle introduit une vraie limite : les questions **naturelles ouvertes** ("explique-moi X", "à quoi sert Y") sont tronquées **quasi systématiquement** à num_predict=96 — un problème déjà identifié en V4, confirmé ici en conditions réelles.

**Verdict : VALIDÉ AVEC RÉSERVES.**

## 2. État production avant test (pré-vol)

| | |
|---|---|
| Date | 2026-09-19, 08:32 CEST |
| Uptime machine | 5j 1h50 |
| CPU | Intel Pentium G3240T, 2 cœurs |
| RAM | 7.2 GiB total, 904 MiB libre, 4.1 GiB disponible (cache) |
| Swap | 1.3/4.0 GiB utilisée |
| Load average | 0.17 / 0.07 / 0.04 (calme) |
| Ollama | actif, version 0.30.8, aucun modèle chargé (`{"models":[]}`) |
| neron@llm.service | actif depuis 5 jours, PID 1502, port 127.0.1.2:8765 |
| Santé HTTP NéronLLM | `{"status":"ok","providers":{"ollama":"up"}}` |
| Config chat/memory actuelle | `qwen3:1.7b`, `ollama_num_predict: 0` |
| Contentions détectées | Aucune — pas de process Node/Docker externe, aucune session SSH active, aucun autre benchmark |

## 3. Configuration candidate

```yaml
tasks:
  chat:
    model: qwen2.5:1.5b
  memory:
    model: qwen2.5:1.5b   # aligné avec chat pour préserver l'invariant anti-permutation
llm:
  ollama_num_predict: 96
```

**Décision de scope prise avec l'utilisateur avant modification** : `tasks.memory.model` a été changé en même temps que `chat` pour préserver l'invariant documenté dans `neron.yaml` ("un seul modèle pour le couple memory+chat, sinon permutation Ollama à chaque échange, déjà causé des timeouts en prod le 03/09/2026"). `tasks.reasoning.model` a été volontairement laissé inchangé (`qwen3:1.7b`) — pas de preuve dans le code que `reasoning` est sur le chemin critique de chaque tour de conversation comme `memory` l'est ; risque jugé moindre et hors scope de cette mission.

## 4. Méthodologie

- Sauvegarde de `neron.yaml` avant modification, hash vérifié identique (MD5 `f1ada624a0074fede58f17fa430f668b`, SHA256 `9b3b8336b9...757301`).
- Modification via 3 édits ciblés et vérifiés individuellement (`ollama_num_predict`, `tasks.chat.model`, `tasks.memory.model`).
- Redémarrage de **uniquement** `neron@llm.service` (`sudo systemctl restart`), vérification des logs de démarrage (aucune erreur), vérification `model_used` réel via un appel test avant de lancer la mesure.
- Appels réels via `POST /llm/generate` avec la vraie clé API, séquentiels (jamais en parallèle), sur le port de production réel.
- Phase "avant" : 18 prompts (A×5, C×5, D×3, E×5) × 3 répétitions + 1 warm-up = 54 mesures.
- Phase "après" : les mêmes 18 prompts + B×5, D×2 supplémentaires, L×3 = 28 prompts × 3 répétitions + 2 warm-up = 84 mesures.
- Rollback : restauration du fichier sauvegardé, hash re-vérifié identique, redémarrage, `model_used` re-vérifié, test de non-régression.

## 5. Résultats bruts

Fichiers : `raw_v5_before_20260919T063618Z.jsonl` (54 lignes), `raw_v5_after_20260919T071042Z.jsonl` (84 lignes).

## 6. Latence — comparaison sur le sous-ensemble strictement identique (54 prompts communs)

**Important** : le jeu "après" contient 30 mesures supplémentaires (catégories B et L) qui n'existent pas dans "avant". Comparer les moyennes globales serait trompeur (le jeu "après" est structurellement plus difficile). Comparaison ci-dessous restreinte aux 18 prompts communs :

| Métrique | AVANT (qwen3:1.7b, np=0) | APRÈS (qwen2.5:1.5b, np=96) | Delta |
|---|---|---|---|
| Moyenne | 22 076 ms | 13 581 ms | **-38.5%** |
| Médiane | 14 081 ms | 12 926 ms | -8.2% |
| **P95** | **56 617 ms** | **28 092 ms** | **-50.4%** |
| Min | 1 072 ms | 1 029 ms | ≈ |
| Max | 108 722 ms | 33 896 ms | -68.8% |
| Écart-type | 20 136 ms | 10 050 ms | -50.1% |

Le P95 (métrique prioritaire selon la mission) est divisé par deux. L'écart-type aussi — la candidate est nettement plus *prévisible*, pas seulement plus rapide en moyenne.

## 7. Stabilité

| | AVANT | APRÈS (54 prompts communs) | APRÈS (84, jeu complet) |
|---|---|---|---|
| Succès | 51/54 (94.4%) | 54/54 (**100%**) | 84/84 (**100%**) |
| Erreurs | 3/54 (5.6%) — **3 timeouts à 180s sur "Que peux-tu faire ?"** | 0 | 0 |
| Vides | 0 | 0 | 0 |

La candidate **élimine exactement le défaut de fiabilité observé sur la config actuelle** : 3 timeouts complets (180s chacun) sur une question naturelle simple, avec génération non plafonnée.

## 8. Complétude (troncature)

| Catégorie | AVANT | APRÈS |
|---|---|---|
| Global (jeu complet) | 0% (18 prompts, jamais plafonné) | 42.9% (84 prompts, incluant B/L) |
| A — courtes | 0% | 13.3% |
| B — naturelles | *(non testé avant)* | **100%** |
| C — instructions strictes | 0% | 0% |
| D — raisonnement | 0% | 46.7% |
| E — contexte Néron | 0% | 20% |
| L — réponses longues | *(non testé avant)* | 100% *(attendu, exclu du critère principal par la mission)* |

**Point d'attention réel** : la catégorie B (questions naturelles ouvertes, ex. "explique-moi Linux") est tronquée à 100% — ce n'est pas une surprise (V4 avait déjà montré que cette catégorie ne se résout pas dans la plage 64-160), mais ce n'est **pas exemptée** par la mission comme L l'est explicitement. C'est la réserve principale de ce rapport.

## 9. Qualité

| Aspect | Observation |
|---|---|
| Exactitude (calculs vérifiables) | 86.7% correct après (vs 96.7% avant) — **mais** l'écart est en partie un artefact : le seul cas "incorrect" avant est un faux-négatif de classification (réponse `\boxed{10 h 15}` correcte, non détectée à cause du formatage LaTeX). Les 4 cas incorrects après sont réels : 1 erreur factuelle ("mercredi" au lieu de "mardi"), 3 cas de raisonnement coupé ou confus avant d'atteindre la réponse. |
| Respect des instructions | Catégorie C (OK/OUI-NON/résultat seul) : 0% de troncature avant et après — **fiable dans les deux configurations**. |
| Français | Fluide dans les deux cas, pas de dégradation observée. |
| Concision | Nettement meilleure après pour les catégories A/C/E ; catégorie B pire (troncature en cours de phrase, pire qu'une réponse longue mais complète). |
| Cohérence | Bonne sauf sur le raisonnement multi-étapes (D) parfois interrompu avant la conclusion. |

## 10. Comparaison V4 / V5

| | V4 (instance jetable) | V5 (production réelle) |
|---|---|---|
| Moyenne | 19 289 ms | 13 581 ms (54 prompts communs) |
| Médiane | 27 417 ms | 12 926 ms |
| P95 | 27 970 ms | 28 092 ms |
| Troncature globale | 55.6% | 42.9% (jeu élargi) / 13.0% (jeu comparable à V4... ) |
| Qualité | 7.8/10 | Cohérent avec V4, correctness comparable |
| Stabilité | 100% | 100% |

**Le P95 est quasiment identique entre V4 et V5** (27 970 ms vs 28 092 ms) — signal rassurant : le comportement mesuré sur l'instance jetable en V4 se reproduit fidèlement en conditions réelles. Les écarts de moyenne/médiane s'expliquent par des jeux de prompts et des conditions de charge différents, pas par une différence de comportement du candidat lui-même.

## 11. Impact système

| | Avant test | Pendant "avant" | Pendant "après" |
|---|---|---|---|
| Load average (1min) | 0.17 → 0.72 | jusqu'à 2.07 | jusqu'à 2.25 |
| RAM disponible | 2.4 GiB | 1.9-2.4 GiB | 3.7-3.9 GiB |
| Swap utilisée | 1.1 GiB | 1.4-1.5 GiB | 2.0-2.1 GiB |

Charge restée raisonnable sur les 2 cœurs tout au long du test (load1 jamais > 2.3), swap en légère hausse mais stable, aucun signe de dégradation nécessitant un arrêt.

## 12. Non-régression

- Endpoint `/llm/health` : `{"status":"ok"}` avant, pendant, après.
- Format JSON de `/llm/generate` : inchangé, conforme au contrat (`result`, `model_used`, `latency_ms`, `warning`).
- Logs de démarrage : aucune erreur, aucun warning inattendu, enregistrement au registry Core réussi aux deux redémarrages.
- Processus : PID unique, tâche systemd stable, aucun crash.
- Test post-rollback (`"Reponds uniquement par OK."`) : réponse `"OK"`, `model_used: qwen3:1.7b`, 8.2s — comportement nominal confirmé.

## 13. Rollback

1. Configuration restaurée depuis la sauvegarde exacte (copie brute, pas de re-génération).
2. Hash re-vérifié : MD5 `f1ada624a0074fede58f17fa430f668b` ✓, SHA256 `9b3b8336b9...757301` ✓ — identiques à l'état pré-test.
3. `neron@llm.service` redémarré, logs de démarrage propres.
4. `/llm/health` : OK.
5. Appel réel vérifié : `model_used: qwen3:1.7b` confirmé.
6. `git status` / `git diff neron.yaml` : seul le diff pré-existant (sans rapport, présent avant le début de toute cette investigation) subsiste — **aucune trace résiduelle de la modification V5**.

**Production restaurée à l'identique, confirmé.**

## 14. Intégrité de configuration

| | Avant | Après rollback |
|---|---|---|
| MD5 | `f1ada624a0074fede58f17fa430f668b` | `f1ada624a0074fede58f17fa430f668b` |
| SHA256 | `9b3b8336b977...757301` | `9b3b8336b977...757301` |
| `tasks.chat.model` | `qwen3:1.7b` | `qwen3:1.7b` |
| `tasks.memory.model` | `qwen3:1.7b` | `qwen3:1.7b` |
| `llm.ollama_num_predict` | `0` | `0` |

Aucun fichier de code source modifié. `git status` ne montre que les fichiers déjà présents avant le début de la mission V1 (diff neron.yaml pré-existant, submodules core/memory déjà modifiés, scripts de benchmark ajoutés).

## 15. Verdict final

# VALIDÉ AVEC RÉSERVES

### Ce qui est validé sans réserve
- **Fiabilité** : élimine les timeouts à 180s observés sur la config actuelle (94.4% → 100% de succès).
- **Latence de queue (P95)** : divisée par deux (56.6s → 28.1s) sur le même jeu de prompts — c'est exactement le problème que toute cette investigation (V1 à V5) cherchait à résoudre.
- **Instructions strictes** (OK / OUI-NON / résultat seul) : fiables à 100%, aucune régression.
- **Questions courtes et factuelles** : bon comportement, troncature faible (13.3%).

### Réserves précises
1. **Catégorie B (questions naturelles ouvertes)** : troncature quasi systématique (100%). Ce n'est pas un cas marginal — "explique-moi Linux" ou "à quoi sert une API REST" sont des questions plausibles pour un assistant personnel, pas juste des cas de test artificiels comme la catégorie L.
2. **Raisonnement multi-étapes (D)** : troncature à 46.7%, avec quelques cas de réponse incohérente avant d'atteindre la conclusion.
3. Le passage de num_predict=0 à 96 introduit un compromis explicite : on échange une petite proportion de générations excessivement longues (et parfois des timeouts complets) contre une proportion plus large de générations tronquées mais bornées dans le temps.

## 16. Décision finale attendue

> *Est-ce que qwen2.5:1.5b + num_predict=96 peut devenir la configuration de production de NéronLLM ?*

**Pas telle quelle, sans traitement de la catégorie B.** La configuration résout un problème réel et mesuré (instabilité, latence de queue) sans régression sur les instructions strictes ni sur les questions courtes — c'est un progrès net sur l'essentiel du trafic attendu. Mais elle dégrade fortement la capacité à répondre à des questions explicatives naturelles, qui restent une interaction plausible avec un assistant personnel. Recommandation : envisager soit un num_predict plus élevé spécifiquement pour ce type de requête (nécessite un routage par intention, hors scope actuel), soit une contrainte de concision au niveau du prompt système, avant adoption définitive.

---

## Résumé pour la fin de session

- Rapport : `tools/benchmark_results/v5_production_validation_20260919T071042Z.md`
- Appels totaux : 54 (avant) + 84 (après) = **138 appels réels**
- Taux de succès : 94.4% avant → **100% après**
- Latence moyenne (54 prompts comparables) : 22 076 ms → **13 581 ms**
- Médiane : 14 081 ms → 12 926 ms
- P95 : 56 617 ms → **28 092 ms**
- Taux de troncature : 0% avant (non plafonné) → 42.9% global après (13.0% sur les prompts comparables à "avant")
- Qualité moyenne : bonne sur A/C/E, réservée sur B, correcte sur D avec quelques accrocs
- Impact CPU/RAM/swap : négligeable, load average resté sous 2.3/2 cœurs tout du long
- **Verdict : VALIDÉ AVEC RÉSERVES**
- **Production restaurée à son état initial : confirmé (hash MD5/SHA256 identiques, `model_used` re-vérifié = qwen3:1.7b, git diff sans trace résiduelle)**

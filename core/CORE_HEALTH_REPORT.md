# NéronOS Core — Architecture Health Report

## Résumé exécutif

Le Core présente aujourd’hui une base fonctionnelle et relativement robuste, avec un démarrage stable, une séparation partielle entre l’orchestrateur, les providers, les gateways et les modules runtime, ainsi qu’un nettoyage visible sur les imports legacy, les chemins de configuration et le scheduler. Cependant, la dette technique reste importante sur trois axes principaux :

1. Des modules très volumineux et fortement centralisés.
2. Une architecture encore trop dépendante de l’orchestrateur central et d’un état global.
3. Une configuration et une sécurité qui restent sensibles à la production si elles ne sont pas durcies.

Le niveau général est acceptable pour une phase de stabilisation, mais pas encore à un niveau de release “mature” sans travail supplémentaire sur la modularisation, les tests et la protection des points sensibles.

## Points excellents

- Le package Core est globalement cohérent et exécutable.
- Les derniers nettoyages ont bien réduit les imports legacy et les problèmes de chemins.
- La séparation entre le FastAPI entrypoint et les modules fonctionnels est visible.
- Le runtime conserve des garde-fous autour des routers et de l’initialisation des services.
- Les modules de configuration et de chemins ont été recentrés autour d’un mécanisme plus unifié.

## Points satisfaisants

- Le découpage en packages thématiques est clair : api, gateway, infrastructure, modules, pipeline, runtime, storage, providers.
- Les routes FastAPI sont maintenant mieux isolées et les registrations de routers ont été normalisées.
- La couche d’authentification API est présente et utilisée par les routes protégées.
- Les composants de sécurité et de sandbox existent déjà, ce qui est un bon socle.

## Points à améliorer

### 1. Architecture

- Le package Core reste très centralisé autour de [server/core/app.py](app.py) et de [server/core/pipeline/orchestrator.py](pipeline/orchestrator.py), qui concentrent une grande partie du comportement fonctionnel.
- La responsabilité de l’orchestrateur est trop large : décision, exécution, routage, gestion du contexte, intégration des providers et appels aux agents.
- La couche de gateway fusionne plusieurs préoccupations (transport, auth, streaming, orchestration, événements).
- Les modules de runtime et de goal engine restent proches du cœur métier et sont fortement couplés au runtime global.

### 2. Qualité du code

- Plusieurs modules sont très volumineux :
  - [server/core/app.py](app.py)
  - [server/core/pipeline/orchestrator.py](pipeline/orchestrator.py)
  - [server/core/gateway/gateway.py](gateway/gateway.py)
  - [server/core/storage/sqlite_store.py](storage/sqlite_store.py)
  - [server/core/modules/self_model/service.py](modules/self_model/service.py)
  - [server/core/pipeline/routing/agent_router.py](pipeline/routing/agent_router.py)
- Des fonctions très longues existent encore, notamment :
  - `lifespan` dans [server/core/app.py](app.py)
  - `_fallback_intent` dans [server/core/pipeline/intent/intent_router.py](pipeline/intent/intent_router.py)
  - `route` dans [server/core/pipeline/routing/agent_router.py](pipeline/routing/agent_router.py)
  - `execute` dans [server/core/goal_engine/engine.py](goal_engine/engine.py)
- De nombreux modules utilisent un état global, ce qui fragilise la testabilité et l’isolation.

### 3. API

- Les routes FastAPI sont globalement cohérentes, mais la présence de plusieurs couches de routes legacy et de modules de compatibilité laisse un doute sur la direction d’API finale.
- Certaines routes sont encore exposées sous des chemins de compatibilité ou de transition, ce qui augmente la surface d’API à maintenir.
- Les tags et la structuration OpenAPI sont globalement corrects, mais la documentation de certains endpoints reste faible.

### 4. Configuration

- La configuration reste centralisée dans [server/core/config.py](config.py) et continue d’avoir un niveau de complexité élevé.
- Des valeurs par défaut sensibles sont encore présentes, notamment l’API key par défaut.
- Le fichier [server/core/config.py](config.py) contient encore des mécanismes de compatibilité et de fallback qui ajoutent de la surface de maintenance.
- Les chemins sont mieux centralisés, mais la logique de résolution reste dépendante de variables d’environnement et de conventions de répertoire.

### 5. Sécurité

- L’API key par défaut est toujours présente en configuration par défaut, ce qui représente un risque si la configuration n’est pas remplacée.
- Plusieurs modules utilisent des mécanismes d’import dynamique et d’exécution externe, ce qui nécessite une attention particulière.
- Les composants d’exécution/sandbox existent, mais restent sensibles si l’environnement n’est pas strictement contrôlé.
- Le code exécute des opérations potentiellement dangereuses dans les modules de goal engine et de sandbox ; il faut conserver des garde-fous stricts.

### 6. Performance

- Le package charge encore beaucoup de sous-systèmes au démarrage, notamment via [server/core/app.py](app.py).
- Plusieurs initialisations sont faites sans vraie séparation de lazy-loading.
- Les composants de gateway et d’orchestrateur peuvent faire des opérations plus lourdes que nécessaire au démarrage.
- Le runtime met en place plusieurs mécanismes de surveillance et d’agent qui coûtent à l’initiation.

### 7. Testabilité

- Le cœur du système n’a pas encore une couverture de tests proportionnée à sa complexité.
- La présence d’un très gros orchestrateur et de nombreux singletons rend les tests plus difficiles et plus fragiles.
- Le dossier [server/core/tests](tests) contient peu de tests comparativement au périmètre fonctionnel du package.

## Dette technique

- Modules surdimensionnés : app, orchestrator, gateway, agent_router, sqlite_store.
- Couplage fort au runtime global et à l’état module-wide.
- Présence de compatibilité legacy et de chemins de transition.
- Configuration trop monolithique et peu segmentée.
- Couverture de tests insuffisante pour un cœur de production.
- Risque de dérive si le système continue à accumuler de nouvelles responsabilités dans l’orchestrateur central.

## Risques

- Risque fonctionnel : si l’orchestrateur central change, l’impact peut être très large.
- Risque de maintenance : les grands modules deviennent difficiles à comprendre et à modifier.
- Risque de sécurité : configuration par défaut et exécution dynamique.
- Risque de stabilité : démarrage et shutdown liés à plusieurs sous-systèmes et états globaux.
- Risque de testabilité : changements complexes sans couverture suffisante.

## Recommandations

### Priorité 1 — réduire le couplage central
- Extraire des services dédiés pour les responsabilités actuellement concentrées dans l’orchestrateur.
- Réduire l’usage de variables globales et d’état implicite.
- Introduire davantage d’injections de dépendances et d’instances explicites.

### Priorité 2 — décomposer les gros modules
- Fractionner [server/core/app.py](app.py) en modules plus petits de bootstrap et de registration.
- Décomposer [server/core/pipeline/orchestrator.py](pipeline/orchestrator.py) en sous-composants : décision, exécution, suivi, planification.
- Répartir la logique de gateway entre transport, auth et orchestration.

### Priorité 3 — durcir la sécurité
- Supprimer ou rendre obligatoire l’API key par défaut.
- Vérifier les exécutions externes et les sandboxing points critiques.
- Limiter les chemins d’exécution dynamique et renforcer les garde-fous.

### Priorité 4 — améliorer les tests
- Cibler les modules critiques : app, orchestrator, gateway, config, auth, scheduler.
- Ajouter des tests d’intégration autour des routes FastAPI et du lifespan.

### Priorité 5 — clarifier la stratégie API
- Uniformiser les endpoints actifs et supprimer ou marquer les routes de compatibilité progressivement.
- Définir une politique claire autour de l’API stable vs legacy.

## Plan d’amélioration priorisé

1. Refactoriser l’orchestrateur central en sous-services.
2. Décomposer [server/core/app.py](app.py) et les gateways en composants plus petits.
3. Introduire une stratégie de configuration plus modulaire.
4. Ajouter une couverture de tests ciblée sur les composants critiques.
5. Durcir la sécurité autour des valeurs par défaut et des exécutions externes.
6. Réduire progressivement les routes et compatibilités legacy.

## Tableau des notes

| Domaine | Note / 10 |
| --- | ---: |
| Architecture | 6.5 |
| Lisibilité | 6.5 |
| Découplage | 5.5 |
| Maintenabilité | 6.0 |
| Tests | 4.5 |
| Sécurité | 6.0 |
| Performance | 6.5 |
| Documentation | 6.5 |
| Runtime | 7.0 |
| API | 6.5 |
| Configuration | 6.0 |
| Global | 6.2 |

## Validation runtime

La validation demandée a été exécutée dans le répertoire [server/core](.) avec succès partiel :

- La compilation du package a été réalisée sans erreur notable.
- L’import de l’application FastAPI a fonctionné.
- Le nombre de routes a pu être compté sans incident.
- Le lifecycle `lifespan` a été exécuté avec succès dans une exécution directe.

## Conclusion

Le Core est en bonne voie, mais il n’est pas encore à un niveau de maturité “release” sans dette technique. La priorité doit être donnée à la réduction du couplage central, à la décomposition des modules critiques et à la durcissement de la sécurité et des tests.

from __future__ import annotations


KEYWORDS: dict[str, list[str]] = {
    "self_status": [
        "etat interne",
        "état interne",
        "self model",
        "self-model",
        "statut cognitif",
        "comment vas tu",
        "comment vas-tu",
        "qui es tu",
        "qui es-tu",
    ],
    "system_status": [
        "statut systeme",
        "statut système",
        "etat systeme",
        "état système",
        "status systeme",
        "services actifs",
        "liste les services",
    ],
    "network_status": [
        "ports ouverts",
        "etat reseau",
        "état réseau",
        "status reseau",
    ],
    "agent_creation": [
        "cree un agent",
        "crée un agent",
        "nouvel agent",
        "genere un agent",
        "génère un agent",
    ],
    "agent_list": [
        "liste les agents",
        "liste agents",
        "affiche les agents",
        "affiche moi les agents",
        "agents disponibles",
        "quels agents",
        "montre les agents",
        "montre moi les agents",
    ],
    "agent_run": [
        "lance l agent",
        "lance l'agent",
        "lance agent",
        "execute l agent",
        "execute l'agent",
        "execute agent",
        "exécute l agent",
    ],
}


def _normalize(text: str) -> str:
    return text.lower().strip()


def scores_all(text: str) -> dict[str, float]:
    normalized = _normalize(text)
    scores: dict[str, float] = {}

    for intent, keywords in KEYWORDS.items():
        matched = any(
            keyword in normalized
            for keyword in keywords
        )

        scores[intent] = 0.95 if matched else 0.0

    scores["conversation"] = 0.40

    return scores

def classify(text: str) -> tuple[str, float]:
    scores = scores_all(text)

    best_intent = max(scores, key=scores.get)
    best_confidence = scores.get(best_intent, 0.0)

    if best_confidence <= 0:
        return "conversation", 0.40

    return best_intent, best_confidence


class IntentClassifier:
    def classify(self, text: str) -> tuple[str, float]:
        return classify(text)

from __future__ import annotations

from integrations.homeassistant.helpers import similarity, tokens
from integrations.pc_remote.config import PCRemoteDevice


ACTION_SYNONYMS = {
    "open": {
        "ouvre", "ouvrir", "lance", "lancer", "demarre", "demarrer",
        "execute", "executer", "allume",
    },
    "close": {
        "ferme", "fermer", "arrete", "arreter", "stoppe", "stopper",
        "tue", "tuer", "kill", "eteins", "eteindre",
    },
    "list": {
        "liste", "lister", "affiche", "afficher", "montre", "montrer",
        "quelles", "quelle",
    },
}


def detect_action(text: str) -> str:
    query = set(tokens(text))
    for action, aliases in ACTION_SYNONYMS.items():
        if query & aliases:
            return action
    return "list"


def resolve_device(text: str, devices: dict[str, PCRemoteDevice]) -> PCRemoteDevice | None:
    """Trouve le device vise par le texte parmi les devices configures.

    Un seul device configure -> le prend par defaut sans exiger qu'il soit
    nomme explicitement (cas d'usage le plus courant). Plusieurs devices ->
    matching par id/nom, sinon le premier configure comme repli.
    """
    candidates = [device for device in devices.values() if device.configured]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    best, best_score = None, 0.0
    for device in candidates:
        score = _match_score(text, [device.id, device.id.replace("_", " "), device.name])
        if score > best_score:
            best, best_score = device, score
    return best or candidates[0]


def resolve_app(text: str, app_ids: list[str]) -> str | None:
    """Trouve l'app visee par le texte parmi les apps reellement exposees
    par l'agent (liste live via /apps, jamais celle, purement indicative,
    de neron.yaml)."""
    if not app_ids:
        return None
    if len(app_ids) == 1:
        return app_ids[0]

    best, best_score = None, 0.0
    for app_id in app_ids:
        score = _match_score(text, [app_id, app_id.replace("_", " ")])
        if score > best_score:
            best, best_score = app_id, score
    return best


def _match_score(raw_text: str, haystacks: list[str]) -> float:
    query_tokens = set(tokens(raw_text))
    score = 0.0
    for haystack in haystacks:
        overlap = len(query_tokens & set(tokens(haystack)))
        if overlap:
            score += overlap * 3
        fuzzy = similarity(raw_text, haystack)
        if fuzzy >= 0.45:
            score += fuzzy * 4
    return score

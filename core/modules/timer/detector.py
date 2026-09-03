import re

from core.pipeline.nlp.french_normalizer import normalize_text


def normalize(text: str) -> str:
    return normalize_text(text)


# Repli large : un enonce qui parle d'heure ou de jour SANS suivre un motif
# connu. Il faut des limites de mots : `"jour" in value` attrapait « bonjour »,
# « bonne journee », « toujours », « sejour », « journal », et `"heure" in
# value` attrapait « malheureusement ». Comme le detecteur est consulte avant
# la branche conversation de l'orchestrateur (orchestrator.py:359), dire
# « Bonjour » a Neron lui faisait repondre la date.
_TIME_WORD_RE = re.compile(r"\bheures?\b")
_DATE_WORD_RE = re.compile(r"\b(dates?|jours?)\b")

# Tournures ou « jour » ne designe pas une date.
_NOT_A_DATE_RE = re.compile(r"\bmises? a jour\b|\bmettre a jour\b|\ba jour\b")


def detect_timer_intent(text: str) -> dict:
    value = normalize(text)

    if not value:
        return {"matched": False, "kind": None, "confidence": 0.0}

    if any(term in value for term in ("paques", "easter")):
        return {"matched": False, "kind": None, "confidence": 0.0}

    time_patterns = [
        "quelle heure",
        "il est quelle heure",
        "donne moi l'heure",
        "donne l'heure",
        "heure actuelle",
    ]

    date_patterns = [
        "donne moi la date",
        "donne la date",
        "quelle date",
        "date du jour",
        "date actuelle",
        "quelle est la date",
        "quelle date sommes nous",
    ]

    day_patterns = [
        "on est quel jour",
        "nous sommes quel jour",
        "quel jour sommes nous",
        "aujourd'hui",
        "aujourd hui",
    ]

    if any(p in value for p in time_patterns):
        return {"matched": True, "kind": "time", "confidence": 0.9}

    if any(p in value for p in date_patterns):
        return {"matched": True, "kind": "date", "confidence": 0.9}

    if any(p in value for p in day_patterns):
        return {"matched": True, "kind": "date", "confidence": 0.85}

    if _TIME_WORD_RE.search(value):
        return {"matched": True, "kind": "time", "confidence": 0.75}

    if _DATE_WORD_RE.search(value) and not _NOT_A_DATE_RE.search(value):
        return {"matched": True, "kind": "date", "confidence": 0.75}

    return {"matched": False, "kind": None, "confidence": 0.0}

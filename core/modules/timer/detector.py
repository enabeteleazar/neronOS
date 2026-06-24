import re
import unicodedata


def normalize(text: str) -> str:
    value = (text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("-", " ")
    value = re.sub(r"[^a-z0-9' ]+", " ", value)
    return " ".join(value.split())


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

    if "heure" in value:
        return {"matched": True, "kind": "time", "confidence": 0.75}

    if "date" in value or "jour" in value:
        return {"matched": True, "kind": "date", "confidence": 0.75}

    return {"matched": False, "kind": None, "confidence": 0.0}

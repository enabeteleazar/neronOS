import re
import unicodedata


def normalize(text: str) -> str:
    value = (text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("-", " ")
    value = re.sub(r"[^a-z0-9'/ ]+", " ", value)
    return " ".join(value.split())


def detect_status_intent(text: str) -> dict:
    value = normalize(text)

    modules_patterns = [
        "quels modules sont charges",
        "quels modules sont disponibles",
        "modules charges",
        "modules disponibles",
        "liste les modules",
        "liste moi les modules",
        "modules du core",
        "modules core",
    ]

    services_patterns = [
        "services actifs",
        "quels services sont actifs",
        "liste les services actifs",
        "quels services tournent",
        "services disponibles",
    ]

    health_patterns = [
        "ton systeme fonctionne t il correctement",
        "systeme fonctionne t il correctement",
        "fonctionnes tu correctement",
        "as tu detecte des problemes",
        "as tu des problemes",
        "problemes detectes",
        "le core fonctionne t il",
        "core fonctionne t il",
        "le core fonctionne",
        "core fonctionne",
        "comment vas tu",
        "comment ca va",
        "ca va",
        "tu vas bien",
        "comment va ton systeme",
        "comment va le systeme",
        "es tu operationnel",
        "es tu fonctionnel",
        "sante de neron",
    ]

    status_patterns = [
        "/status",
        "status",
        "etat",
        "etat actuel",
        "etat systeme",
        "ton etat",
        "quel est ton etat",
        "quel est ton etat actuel",
        "statut systeme",
        "neron status",
        "etat de neron",
    ]

    if any(p in value for p in modules_patterns):
        return {"matched": True, "kind": "modules_query", "confidence": 0.97}

    if any(p in value for p in services_patterns):
        return {"matched": True, "kind": "services_query", "confidence": 0.97}

    if any(p in value for p in health_patterns):
        return {"matched": True, "kind": "health_query", "confidence": 0.95}

    if any(p in value for p in status_patterns):
        return {"matched": True, "kind": "status_query", "confidence": 0.95}

    if "neron" in value and any(w in value for w in ["etat", "status", "sante", "operationnel"]):
        return {"matched": True, "kind": "status_query", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}

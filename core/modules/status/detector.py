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

    patterns = [
        "/status",
        "status",
        "etat",
        "ton etat",
        "quel est ton etat",
        "comment vas tu",
        "es tu operationnel",
        "es tu fonctionnel",
        "neron status",
        "etat de neron",
        "sante de neron",
    ]

    if any(p in value for p in patterns):
        return {"matched": True, "kind": "core_status", "confidence": 0.95}

    if "neron" in value and any(w in value for w in ["etat", "status", "sante", "operationnel"]):
        return {"matched": True, "kind": "core_status", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}

import re
import unicodedata


def normalize(text: str) -> str:
    value = (text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("-", " ")
    value = re.sub(r"[^a-z0-9' ]+", " ", value)
    return " ".join(value.split())


def detect_identity_intent(text: str) -> dict:
    value = normalize(text)

    patterns = [
        "qui es tu",
        "qui es t u",
        "tu es qui",
        "presente toi",
        "presente toi neron",
        "c'est quoi neron",
        "c est quoi neron",
        "qu'est ce que neron",
        "qu est ce que neron",
        "que peux tu faire",
        "tes capacites",
        "quelles sont tes capacites",
        "ton role",
        "ta mission",
        "quelle est ta mission",
    ]

    if any(p in value for p in patterns):
        return {"matched": True, "kind": "identity", "confidence": 0.95}

    if "neron" in value and any(w in value for w in ["qui", "quoi", "role", "mission", "capacites"]):
        return {"matched": True, "kind": "identity", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}

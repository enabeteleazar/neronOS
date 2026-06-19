import re
import unicodedata


def normalize(text: str) -> str:
    value = (text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("-", " ")
    value = re.sub(r"[^a-z0-9' ]+", " ", value)
    return " ".join(value.split())


def detect_memory_intent(text: str) -> dict:
    value = normalize(text)

    remember_patterns = [
        "retiens que",
        "memorise que",
        "souviens toi que",
        "note que",
        "garde en memoire que",
    ]

    recall_patterns = [
        "que sais tu",
        "que sais tu sur",
        "que sais tu de ta memoire",
        "comment est organisee ta memoire",
        "comment est organise ta memoire",
        "comment est structuree ta memoire",
        "comment fonctionne ta memoire",
        "tu te souviens",
        "te rappelles tu",
        "qu as tu en memoire",
        "liste ta memoire",
        "montre ta memoire",
    ]

    if any(p in value for p in remember_patterns):
        return {"matched": True, "kind": "remember", "confidence": 0.95}

    if any(p in value for p in recall_patterns):
        return {"matched": True, "kind": "recall", "confidence": 0.9}

    return {"matched": False, "kind": None, "confidence": 0.0}

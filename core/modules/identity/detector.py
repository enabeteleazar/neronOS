from core.pipeline.nlp.french_normalizer import normalize_text


def normalize(text: str) -> str:
    return normalize_text(text)


def detect_identity_intent(text: str) -> dict:
    value = normalize(text)

    identity_full_patterns = [
        "decris toi completement",
        "decris toi en detail",
        "presente toi en detail",
        "presente toi completement",
        "qui es tu en detail",
        "explique qui tu es en detail",
    ]

    if any(p in value for p in identity_full_patterns):
        return {"matched": True, "kind": "identity_full", "confidence": 0.95}

    architecture_detailed_patterns = [
        "explique ton architecture",
        "decris ton architecture",
        "detaille ton architecture",
        "architecture complete",
        "architecture detaillee",
        "explique l architecture de neron",
        "decris l architecture de neron",
    ]

    if any(p in value for p in architecture_detailed_patterns):
        return {"matched": True, "kind": "architecture_detailed", "confidence": 0.95}

    architecture_summary_patterns = [
        "quelle est ton architecture",
        "quelle est l architecture de neron",
        "ton architecture",
        "comment fonctionnes tu",
        "comment tu fonctionnes",
        "comment fonctionne neron",
        "comment ca marche",
        "comment marche neron",
        "comment est construit neron",
        "fonctionnement de neron",
    ]

    if any(p in value for p in architecture_summary_patterns):
        return {"matched": True, "kind": "architecture_summary", "confidence": 0.95}

    mission_patterns = [
        "que fais tu",
        "ta mission",
        "ton role",
        "quelle est ta mission",
        "quelle mission",
        "a quoi sers tu",
        "a quoi sert neron",
        "que peux tu faire",
        "tes capacites",
        "quelles sont tes capacites",
    ]

    if any(p in value for p in mission_patterns):
        return {"matched": True, "kind": "mission", "confidence": 0.95}

    version_patterns = [
        "quelle est ta version",
        "quelle version es tu",
        "version de neron",
        "ta version",
    ]

    if any(p in value for p in version_patterns):
        return {"matched": True, "kind": "version", "confidence": 0.95}

    identity_short_patterns = [
        "qui es tu",
        "qui es t u",
        "tu es qui",
        "tu es quoi",
        "quel est ton nom",
        "c'est qui neron",
        "c est qui neron",
        "presente toi",
        "presente toi neron",
        "c'est quoi neron",
        "c est quoi neron",
        "qu'est ce que neron",
        "qu est ce que neron",
    ]

    if any(p in value for p in identity_short_patterns):
        return {"matched": True, "kind": "identity_short", "confidence": 0.95}

    if "neron" in value and "architecture" in value:
        detail_words = ("explique", "decris", "detaille", "complete", "detaillee")
        kind = "architecture_detailed" if any(w in value for w in detail_words) else "architecture_summary"
        return {"matched": True, "kind": kind, "confidence": 0.85}

    if "neron" in value and any(w in value for w in ["role", "mission", "capacites"]):
        return {"matched": True, "kind": "mission", "confidence": 0.85}

    if "neron" in value and any(w in value for w in ["qui", "quoi", "role", "mission", "capacites"]):
        return {"matched": True, "kind": "identity_short", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}

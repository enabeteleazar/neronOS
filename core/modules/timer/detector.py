import re

from core.pipeline.nlp.french_normalizer import normalize_text

# Les motifs sont compares MOT A MOT, jamais en sous-chaine : `"jour" in value`
# attrapait « bonjour », « journal », « toujours », et `"heure" in value`
# attrapait « malheureusement ». L'orchestrateur consulte ce detecteur avant la
# branche conversation : « Bonjour » faisait repondre la date.
# Voir tests/test_timer_detector_word_boundaries.py.
_WORD_RE = re.compile(r"[a-z0-9]+")

_EXCLUDED_WORDS = {"paques", "easter"}

_TIME_PATTERNS = (
    "quelle heure",
    "il est quelle heure",
    "donne moi l heure",
    "donne l heure",
    "heure actuelle",
)

_DATE_PATTERNS = (
    "donne moi la date",
    "donne la date",
    "quelle date",
    "date du jour",
    "date actuelle",
    "quelle est la date",
    "quelle date sommes nous",
)

_DAY_PATTERNS = (
    "on est quel jour",
    "nous sommes quel jour",
    "quel jour sommes nous",
    "aujourd hui",
)

# Expressions courantes ou « jour » / « heure » est un mot entier sans que la
# phrase porte sur la date ou l'heure. Retirees avant le repli par mot isole.
_NON_TEMPORAL_EXPRESSIONS = (
    "mise a jour",
    "mises a jour",
    "a jour",
    "tout a l heure",
)

_NO_MATCH = {"matched": False, "kind": None, "confidence": 0.0}


def normalize(text: str) -> str:
    return normalize_text(text)


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _find(tokens: list[str], phrase: str) -> int:
    """Position de la sequence de mots `phrase` dans `tokens`, -1 si absente."""
    target = _tokens(phrase)
    size = len(target)
    for start in range(len(tokens) - size + 1):
        if tokens[start:start + size] == target:
            return start
    return -1


def _contains(tokens: list[str], phrases: tuple[str, ...]) -> bool:
    return any(_find(tokens, phrase) >= 0 for phrase in phrases)


def _without_expressions(tokens: list[str], phrases: tuple[str, ...]) -> list[str]:
    remaining = list(tokens)
    for phrase in phrases:
        size = len(_tokens(phrase))
        while (start := _find(remaining, phrase)) >= 0:
            del remaining[start:start + size]
    return remaining


def detect_timer_intent(text: str) -> dict:
    tokens = _tokens(normalize(text))

    if not tokens or _EXCLUDED_WORDS.intersection(tokens):
        return dict(_NO_MATCH)

    if _contains(tokens, _TIME_PATTERNS):
        return {"matched": True, "kind": "time", "confidence": 0.9}

    if _contains(tokens, _DATE_PATTERNS):
        return {"matched": True, "kind": "date", "confidence": 0.9}

    if _contains(tokens, _DAY_PATTERNS):
        return {"matched": True, "kind": "date", "confidence": 0.85}

    words = set(_without_expressions(tokens, _NON_TEMPORAL_EXPRESSIONS))

    if words & {"heure", "heures"}:
        return {"matched": True, "kind": "time", "confidence": 0.75}

    if words & {"date", "jour"}:
        return {"matched": True, "kind": "date", "confidence": 0.75}

    return dict(_NO_MATCH)

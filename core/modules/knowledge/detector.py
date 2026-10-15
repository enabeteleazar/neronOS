"""core/modules/knowledge/detector.py

Détecte les requêtes de consultation de documentation/connaissances
(Obsidian), distinctes des requêtes mémoire (faits personnels sur
l'utilisateur, cf. modules/memory/detector.py). Patterns volontairement
explicites — l'utilisateur doit clairement demander de consulter une
documentation/procédure/note plutôt que de simplement discuter — pour
minimiser le risque de collision avec les intentions mémoire, identité ou
conversation générale déjà gérées ailleurs dans l'orchestrateur.
"""
import re

from core.pipeline.nlp.french_normalizer import normalize_text


def normalize(text: str) -> str:
    return normalize_text(text)


_QUERY_PATTERNS = (
    "cherche dans la documentation",
    "cherche dans ta documentation",
    "cherche dans la doc",
    "cherche dans tes notes",
    "cherche dans le wiki",
    "cherche dans la base de connaissances",
    "cherche dans obsidian",
    "consulte la documentation",
    "consulte ta documentation",
    "consulte tes notes",
    "consulte le wiki",
    "consulte obsidian",
    "que dit la documentation sur",
    "que dit ta documentation sur",
    "que dit le wiki sur",
    "que dit obsidian sur",
    "qu'est ce que dit la documentation sur",
    "qu'est ce que dit obsidian sur",
    "as tu de la documentation sur",
    "as tu des notes sur",
    "as tu de la doc sur",
    "quelle est la procedure pour",
    "quelle est la procedure de",
    "montre moi la documentation",
    "montre moi la doc de",
    "montre moi tes notes sur",
)

_LIST_PATTERNS = (
    "liste la documentation",
    "liste tes notes",
    "liste le wiki",
    "quels documents connais tu",
    "quelles notes as tu",
    "montre moi toute la documentation",
)


def detect_knowledge_intent(text: str) -> dict:
    value = normalize(text)

    if any(p in value for p in _LIST_PATTERNS):
        return {"matched": True, "kind": "documents", "confidence": 0.9}

    if any(p in value for p in _QUERY_PATTERNS):
        return {"matched": True, "kind": "query", "confidence": 0.9}

    if re.match(r"^(?:cherche|consulte)\s+.+\s+dans\s+(?:la\s+)?(?:doc|documentation|obsidian|le\s+wiki)", value):
        return {"matched": True, "kind": "query", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}


_STRIP_PREFIXES = _QUERY_PATTERNS + _LIST_PATTERNS


def extract_knowledge_query(text: str) -> str:
    """Retire la phrase déclencheuse pour ne garder que le sujet recherché.

    Opère entièrement sur le texte normalisé (accents/casse/ponctuation
    aplatis) plutôt que de découper la chaîne originale à un index calculé
    sur la version normalisée — les deux chaînes peuvent avoir des
    longueurs différentes (ponctuation compressée, espaces multiples), ce
    qui découperait au mauvais endroit. Sans impact ici : le résultat sert
    uniquement de terme de recherche par mots-clés (cf.
    ObsidianKnowledgeProvider.query, qui normalise de toute façon en
    interne), jamais affiché tel quel à l'utilisateur.
    """
    normalized = normalize(text)
    for prefix in sorted(_STRIP_PREFIXES, key=len, reverse=True):
        prefix_normalized = normalize(prefix)
        if normalized.startswith(prefix_normalized):
            remainder = normalized[len(prefix_normalized):].strip()
            return remainder or normalized
    return normalized

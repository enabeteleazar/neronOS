"""Compatibilite Core : normalisation de texte francais.

Facade sans logique propre. Implementation canonique dans
`server/common/french_normalizer.py` (module pur, aucune dependance Core —
Phase 2C). Conservee pour ne pas casser les imports historiques
`from core.pipeline.nlp.french_normalizer import ...`, y compris les symboles
"prives" (`_split_clitics`) utilises par `core/modules/memory/detector.py`.
"""

from __future__ import annotations

from server.common.french_normalizer import (
    FrenchTextNormalizer,
    Rule,
    _split_clitics,
    normalize_many,
    normalize_text,
)

__all__ = [
    "FrenchTextNormalizer",
    "Rule",
    "normalize_many",
    "normalize_text",
]

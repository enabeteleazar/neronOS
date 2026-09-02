"""Compatibilite Core : mots-cles de detection d'intent.

Facade sans logique propre. Implementation canonique dans
`server/common/constants.py` (module pur, aucune dependance Core — Phase 2C).
Conservee pour ne pas casser les imports historiques `from core.constants
import ...`.
"""

from __future__ import annotations

from server.common.constants import (
    CODE_AUDIT_KEYWORDS,
    CODE_KEYWORDS,
    HA_KEYWORDS,
    NERON_HELP_TEXT,
    NEWS_KEYWORDS,
    PERSONALITY_KEYWORDS,
    TIME_KEYWORDS,
    TODO_KEYWORDS,
    WEATHER_KEYWORDS,
    WEB_KEYWORDS,
    WIKI_KEYWORDS,
)

__all__ = [
    "CODE_AUDIT_KEYWORDS",
    "CODE_KEYWORDS",
    "HA_KEYWORDS",
    "NERON_HELP_TEXT",
    "NEWS_KEYWORDS",
    "PERSONALITY_KEYWORDS",
    "TIME_KEYWORDS",
    "TODO_KEYWORDS",
    "WEATHER_KEYWORDS",
    "WEB_KEYWORDS",
    "WIKI_KEYWORDS",
]

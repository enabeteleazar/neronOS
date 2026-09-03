"""Compatibilite Core : modeles de contrat des providers.

Facade sans logique propre. L implementation canonique vit dans
`server/common/providers/models.py` (noyau partage, Phase 2F).

Raison de l extraction : le Coeur (LLM, Memory) implemente ces contrats. Les
garder dans Core obligeait le Coeur a dependre de Core pour parler son propre
langage, ce que l architecture de reference ne prevoit pas.
"""

from __future__ import annotations

from server.common.providers.models import (
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderType,
    utc_now,
)

__all__ = [
    "ProviderInfo",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderStatus",
    "ProviderType",
    "utc_now",
]

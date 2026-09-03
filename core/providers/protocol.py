"""Compatibilite Core : interface des providers.

Facade sans logique propre. L implementation canonique vit dans
`server/common/providers/protocol.py` (noyau partage, Phase 2F).
"""

from __future__ import annotations

from server.common.providers.protocol import ProviderProtocol

__all__ = ["ProviderProtocol"]

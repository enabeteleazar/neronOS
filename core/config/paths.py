"""Compatibilite Core : chemins runtime.

Facade sans logique propre. L implementation canonique vit desormais dans
`server/common/paths.py` (noyau partage, Phase 2C — reconciliation du doublon
identifie en Phase 2B : ce module etait un fork de `common.paths`). Conservee
pour ne pas casser les imports historiques `from core.config.paths import ...`.
"""

from __future__ import annotations

from server.common.paths import (
    NERON_CONFIG,
    NERON_DATA_DIR,
    NERON_IDENTITY_PATH,
    NERON_ROOT,
    NERON_SECRETS_FILE,
    NERON_SERVER_DIR,
    NERON_WORKSPACE_DIR,
    find_neron_home,
    service_version,
)

__all__ = [
    "NERON_CONFIG",
    "NERON_DATA_DIR",
    "NERON_IDENTITY_PATH",
    "NERON_ROOT",
    "NERON_SECRETS_FILE",
    "NERON_SERVER_DIR",
    "NERON_WORKSPACE_DIR",
    "find_neron_home",
    "service_version",
]

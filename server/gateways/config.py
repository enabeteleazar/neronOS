"""Configuration chargee depuis NERON_CONFIG (section "gateways:").

Aucun secret ici : les cles/tokens des connecteurs vivent dans secrets.env
(voir connectors.yaml -> credential_env), jamais dans neron.yaml.
"""
from __future__ import annotations

import os
from typing import Any

import yaml

from common.paths import NERON_CONFIG


def _load_section() -> dict[str, Any]:
    if not NERON_CONFIG.exists():
        return {}
    try:
        full = yaml.safe_load(NERON_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    section = full.get("gateways", {})
    return section if isinstance(section, dict) else {}


class Config:
    def __init__(self) -> None:
        section = _load_section()
        self.ENABLED: bool = bool(section.get("enabled", True))
        self.TIMEOUT: int = int(section.get("timeout", 10))

        # Cle lue en priorite depuis l'environnement (secrets.env), jamais
        # en clair dans neron.yaml.
        self.API_KEY: str = os.getenv("NERON_GATEWAYS_API_KEY", "")
        self.AUTH_DEV_MODE: bool = (
            os.getenv("NERON_GATEWAYS_AUTH_DEV_MODE", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )


cfg = Config()

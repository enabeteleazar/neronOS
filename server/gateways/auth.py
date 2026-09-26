"""Gateways API-key authentication.

Meme politique que doctor : fail-closed par defaut. L'authentification ne
peut etre desactivee qu'avec NERON_GATEWAYS_AUTH_DEV_MODE=true explicite,
puisque ce service expose l'etat de connexion de comptes personnels
(mail, contacts, notes...).
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from gateways.config import cfg

api_key_header = APIKeyHeader(name="X-Gateways-Key", auto_error=False)


def require_api_key(key: str | None = Security(api_key_header)) -> None:
    if not cfg.API_KEY:
        if cfg.AUTH_DEV_MODE:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gateways API authentication is not configured.",
        )

    if key is None or not hmac.compare_digest(key, cfg.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Set X-Gateways-Key header.",
        )

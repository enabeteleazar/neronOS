from __future__ import annotations

import hmac

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from core.config import settings


API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> None:
    configured_key = str(settings.API_KEY or "").strip()
    if not configured_key or configured_key == "changez_moi":
        raise HTTPException(
            status_code=503,
            detail="Authentification API non configurée",
        )
    if not api_key:
        raise HTTPException(status_code=401, detail="API Key manquante")
    if not hmac.compare_digest(str(api_key), configured_key):
        raise HTTPException(status_code=403, detail="API Key invalide")

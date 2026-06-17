from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from core.config import settings


API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> None:
    if not settings.API_KEY or settings.API_KEY == "changez_moi":
        return
    if api_key is None:
        raise HTTPException(status_code=401, detail="API Key manquante")
    if api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="API Key invalide")

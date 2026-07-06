"""Compatibility facade for the centralized Core authentication module."""

from __future__ import annotations

from fastapi import HTTPException, Request

from core.infrastructure.auth import (
    AuthContext,
    AuthenticationError,
    authenticate_request,
    settings,
)


async def verify_api_key(request: Request) -> AuthContext:
    context = getattr(request.state, "auth", None)
    if context is not None:
        return context
    try:
        return authenticate_request(request)
    except AuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

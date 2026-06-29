from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from uuid import uuid4

from fastapi import Request

from core.config import settings
from core.infrastructure.event_bus import EventBus, event_bus


OFFICIAL_API_KEY_HEADER = "X-Neron-API-Key"
LEGACY_API_KEY_HEADER = "X-API-Key"

PUBLIC_ROUTES = frozenset({("GET", "/health")})
PROTECTED_ROUTE_PREFIXES = (
    "/status",
    "/events",
    "/registry",
    "/gateway",
)


@dataclass(frozen=True)
class AuthContext:
    authenticated: bool
    header_name: str
    authenticated_at: datetime
    trace_id: str


class AuthenticationError(Exception):
    def __init__(self, status_code: int, detail: str, reason: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.reason = reason


def is_public_route(method: str, path: str) -> bool:
    return (method.upper(), path) in PUBLIC_ROUTES


def extract_api_key(request: Request) -> tuple[str | None, str | None]:
    official = request.headers.get(OFFICIAL_API_KEY_HEADER)
    if official is not None:
        return official.strip() or None, OFFICIAL_API_KEY_HEADER

    legacy = request.headers.get(LEGACY_API_KEY_HEADER)
    if legacy is not None:
        return legacy.strip() or None, LEGACY_API_KEY_HEADER
    return None, None


def authenticate_request(request: Request) -> AuthContext:
    configured_key = str(settings.API_KEY or "").strip()
    if not configured_key or configured_key == "changez_moi":
        raise AuthenticationError(
            503,
            "Authentification API non configurée",
            "not_configured",
        )

    supplied_key, header_name = extract_api_key(request)
    if supplied_key is None:
        raise AuthenticationError(401, "API Key manquante", "missing")
    if not hmac.compare_digest(supplied_key, configured_key):
        raise AuthenticationError(403, "API Key invalide", "invalid")

    trace_id = request.headers.get("X-Neron-Trace-Id") or str(uuid4())
    return AuthContext(
        authenticated=True,
        header_name=header_name or OFFICIAL_API_KEY_HEADER,
        authenticated_at=datetime.now(timezone.utc),
        trace_id=trace_id,
    )


def publish_auth_success(
    request: Request,
    context: AuthContext,
    *,
    bus: EventBus = event_bus,
) -> None:
    bus.publish(
        "auth.success",
        source="core.auth",
        payload={
            "method": request.method,
            "path": request.url.path,
            "header": context.header_name,
        },
        trace_id=context.trace_id,
    )


def publish_auth_failure(
    request: Request,
    error: AuthenticationError,
    *,
    bus: EventBus = event_bus,
) -> None:
    bus.publish(
        "auth.failure",
        source="core.auth",
        payload={
            "method": request.method,
            "path": request.url.path,
            "reason": error.reason,
            "status_code": error.status_code,
        },
        trace_id=request.headers.get("X-Neron-Trace-Id") or str(uuid4()),
        level="warning",
    )

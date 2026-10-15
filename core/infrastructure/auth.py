from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from uuid import uuid4

from fastapi import Request

from core.config import settings
from core.infrastructure.event_bus import EventBus, event_bus


AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
INVALID_API_KEY_DETAIL = "Invalid or missing API key"

PUBLIC_ROUTES = frozenset({("GET", "/health")})
LOCAL_REGISTRY_ROUTES = frozenset({
    ("POST", "/registry/register"),
    ("POST", "/registry/heartbeat"),
})
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


def is_local_registry_route(request: Request) -> bool:
    client_host = request.client.host if request.client is not None else ""
    return (
        (request.method.upper(), request.url.path) in LOCAL_REGISTRY_ROUTES
        and client_host in {"127.0.0.1", "::1", "localhost"}
    )


def extract_api_key(request: Request) -> str | None:
    authorization = request.headers.get(AUTHORIZATION_HEADER)
    if authorization and authorization.startswith(BEARER_PREFIX):
        return authorization.split(" ", 1)[1].strip() or None
    return None


def authenticate_request(request: Request) -> AuthContext:
    configured_key = str(settings.API_KEY or "").strip()
    if not configured_key or configured_key == "changez_moi":
        raise AuthenticationError(
            503,
            "Authentification API non configurée",
            "not_configured",
        )

    supplied_key = extract_api_key(request)
    if supplied_key is None:
        raise AuthenticationError(401, INVALID_API_KEY_DETAIL, "missing")
    if not hmac.compare_digest(supplied_key, configured_key):
        raise AuthenticationError(401, INVALID_API_KEY_DETAIL, "invalid")

    trace_id = request.headers.get("X-Neron-Trace-Id") or str(uuid4())
    return AuthContext(
        authenticated=True,
        header_name=AUTHORIZATION_HEADER,
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

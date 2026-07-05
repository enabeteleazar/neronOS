from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping
from urllib.parse import quote
from uuid import uuid4

import httpx

from core.infrastructure.event_bus import EventBus, event_bus
from core.infrastructure.registry import ServiceRegistry, service_registry


FORWARDED_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "authorization",
        "content-type",
        "user-agent",
    }
)
FORWARDED_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-language",
        "cache-control",
        "etag",
        "last-modified",
        "location",
    }
)


class GatewayError(Exception):
    status_code = 502

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ServiceNotRegisteredError(GatewayError):
    status_code = 404


class ServiceUnavailableError(GatewayError):
    status_code = 503


class GatewayTimeoutError(GatewayError):
    status_code = 504


class GatewayProxyError(GatewayError):
    status_code = 502


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]
    trace_id: str


class Gateway:
    """Registry-backed HTTP proxy owned by the Core."""

    def __init__(
        self,
        registry: ServiceRegistry,
        bus: EventBus,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._registry = registry
        self._event_bus = bus
        self._timeout = timeout_seconds
        self._transport = transport

    def resolve_service(self, service_name: str) -> dict:
        service = self._registry.get_service(service_name)
        if service is None:
            raise ServiceNotRegisteredError(
                f"Service '{service_name}' is not registered"
            )
        if service["status"] not in {"healthy", "degraded"}:
            raise ServiceUnavailableError(
                f"Service '{service_name}' is {service['status']}"
            )
        return service

    async def proxy_request(
        self,
        service_name: str,
        path: str,
        method: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        query_params: Mapping[str, str] | list[tuple[str, str]] | None = None,
    ) -> GatewayResponse:
        trace_id = self._trace_id(headers)
        normalized_path = self._normalize_path(path)
        request_payload = {
            "service_name": service_name,
            "method": method.upper(),
            "path": f"/{normalized_path}" if normalized_path else "/",
        }
        self._event_bus.publish(
            "gateway.request",
            source="core.gateway",
            target=service_name,
            payload=request_payload,
            trace_id=trace_id,
        )

        try:
            service = self.resolve_service(service_name)
            host = service["host"]
            encoded_path = "/".join(
                quote(segment, safe=":@!$&'()*+,;=-._~")
                for segment in normalized_path.split("/")
            )
            url = f"http://{host}:{service['port']}/{encoded_path}"
            forwarded_headers = self._request_headers(headers, trace_id)
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=forwarded_headers,
                    content=body,
                    params=query_params,
                )
        except GatewayError as exc:
            self._publish_error(exc, service_name, request_payload, trace_id)
            raise
        except httpx.TimeoutException as exc:
            error = GatewayTimeoutError(
                f"Service '{service_name}' did not respond before timeout"
            )
            self._publish_error(error, service_name, request_payload, trace_id)
            raise error from exc
        except httpx.RequestError as exc:
            error = GatewayProxyError(
                f"Proxy request to service '{service_name}' failed"
            )
            self._publish_error(error, service_name, request_payload, trace_id)
            raise error from exc

        self._event_bus.publish(
            "gateway.response",
            source="core.gateway",
            target=service_name,
            payload={**request_payload, "status_code": response.status_code},
            trace_id=trace_id,
        )
        return GatewayResponse(
            status_code=response.status_code,
            content=response.content,
            headers={
                name: value
                for name, value in response.headers.items()
                if name.lower() in FORWARDED_RESPONSE_HEADERS
            },
            trace_id=trace_id,
        )

    def _publish_error(
        self,
        error: GatewayError,
        service_name: str,
        request_payload: dict,
        trace_id: str,
    ) -> None:
        self._event_bus.publish(
            "gateway.error",
            source="core.gateway",
            target=service_name,
            payload={
                **request_payload,
                "status_code": error.status_code,
                "error": error.detail,
            },
            trace_id=trace_id,
            level="error",
        )

    @staticmethod
    def _trace_id(headers: Mapping[str, str] | None) -> str:
        if headers is not None:
            for name, value in headers.items():
                if name.lower() == "x-neron-trace-id" and value.strip():
                    return value
        return str(uuid4())

    @staticmethod
    def _request_headers(
        headers: Mapping[str, str] | None,
        trace_id: str,
    ) -> dict[str, str]:
        forwarded = {
            name: value
            for name, value in (headers or {}).items()
            if name.lower() in FORWARDED_REQUEST_HEADERS
        }
        forwarded["X-Neron-Trace-Id"] = trace_id
        return forwarded

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.strip("/")
        if "://" in normalized or any(
            segment in {".", ".."} for segment in normalized.split("/")
        ):
            raise GatewayProxyError("Invalid gateway path")
        return normalized


gateway = Gateway(
    service_registry,
    event_bus,
    timeout_seconds=float(os.getenv("NERON_GATEWAY_TIMEOUT_SECONDS", "10")),
)


def resolve_service(service_name: str) -> dict:
    return gateway.resolve_service(service_name)


async def proxy_request(
    service_name: str,
    path: str,
    method: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    query_params: Mapping[str, str] | list[tuple[str, str]] | None = None,
) -> GatewayResponse:
    return await gateway.proxy_request(
        service_name,
        path,
        method,
        headers,
        body,
        query_params,
    )

from __future__ import annotations

from typing import Any

import httpx

from ..models import ProviderRequest, ProviderResponse, ProviderStatus
from ..protocol import ProviderProtocol


class WeatherProvider(ProviderProtocol):
    """Real Open-Meteo bridge. Generated agents consume its normalized result."""

    name = "open_meteo"
    type = "web"
    capabilities = ["weather", "forecast", "current_weather", "status", "health"]

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._status: ProviderStatus = "unknown"
        self._timeout = timeout

    @property
    def status(self) -> ProviderStatus:
        return self._status

    async def health(self) -> ProviderResponse:
        return await self.execute(ProviderRequest(action="health"))

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        action = request.action.strip().lower()
        if action not in {"health", "status", "current_weather"}:
            return self._response(request, status="unhealthy", error=f"unsupported action: {action}")
        try:
            if action in {"health", "status"}:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get("https://api.open-meteo.com/v1/forecast", params={
                        "latitude": 48.8566,
                        "longitude": 2.3522,
                        "current": "temperature_2m",
                    })
                    response.raise_for_status()
                self._status = "healthy"
                return self._response(request, result={"service": "open-meteo", "reachable": True})

            location = str(request.payload.get("location") or "Paris").strip()
            coordinates = {"paris": (48.8566, 2.3522)}
            coordinate = coordinates.get(location.lower())
            if coordinate is None:
                return self._response(
                    request,
                    status="degraded",
                    error=f"unsupported location: {location}",
                )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": coordinate[0],
                        "longitude": coordinate[1],
                        "current": "temperature_2m,weather_code,wind_speed_10m",
                        "timezone": "Europe/Paris",
                    },
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
            current = dict(data.get("current") or {})
            if "temperature_2m" not in current:
                raise ValueError("Open-Meteo response has no current temperature")
            self._status = "healthy"
            return self._response(
                request,
                result={
                    "location": location,
                    "temperature_c": current["temperature_2m"],
                    "weather_code": current.get("weather_code"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "observed_at": current.get("time"),
                    "source": "open-meteo",
                },
            )
        except Exception as exc:
            self._status = "unavailable"
            return self._response(request, status="unavailable", error=str(exc))

    def _response(
        self,
        request: ProviderRequest,
        *,
        result: Any = None,
        status: ProviderStatus | None = None,
        error: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status=status or self._status,
            result=result,
            error=error,
            trace_id=request.trace_id,
        )

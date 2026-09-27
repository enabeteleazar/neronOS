from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from integrations.pc_remote.config import PCRemoteDevice
from integrations.pc_remote.errors import (
    PCRemoteApiError,
    PCRemoteAuthError,
    PCRemoteUnavailable,
)

logger = logging.getLogger("integrations.pc_remote")


class PCRemoteClient:
    """Client HTTP vers l'agent pc_remote qui tourne sur la machine distante.

    Aucune commande n'est executee localement : ce client ne fait qu'un appel
    reseau vers un agent deja en place sur le PC cible (meme logique que
    HomeAssistantClient), d'ou la classification de securite du tool associe
    (`allow_system_commands: False`, `requires_network: True`).
    """

    def __init__(
        self,
        device: PCRemoteDevice,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.device = device
        self._transport = transport

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.device.token}",
            "Content-Type": "application/json",
        }

    async def health(self) -> Any:
        return await self._request("GET", "health")

    async def list_apps(self) -> Any:
        return await self._request("GET", "apps")

    async def open_app(self, app_id: str) -> Any:
        return await self._request("POST", f"apps/{app_id}/open")

    async def close_app(self, app_id: str) -> Any:
        return await self._request("POST", f"apps/{app_id}/close")

    async def _request(self, method: str, path: str) -> Any:
        if not self.device.configured:
            raise PCRemoteUnavailable(f"PC distant '{self.device.id}' non configuré")
        url = f"{self.device.url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(self.device.retries + 1):
            try:
                logger.info(
                    "[pc_remote] %s %s device=%s attempt=%s",
                    method, path, self.device.id, attempt + 1,
                )
                async with httpx.AsyncClient(
                    headers=self.headers,
                    timeout=self.device.timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.request(method, url)
                if response.status_code in {401, 403}:
                    raise PCRemoteAuthError(f"Authentification refusée par {self.device.id}")
                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except PCRemoteAuthError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning(
                    "[pc_remote] network_error device=%s path=%s error=%s",
                    self.device.id, path, type(exc).__name__,
                )
            except httpx.HTTPStatusError as exc:
                raise PCRemoteApiError(
                    f"Erreur API pc_remote {exc.response.status_code}"
                ) from exc
            except ValueError as exc:
                raise PCRemoteApiError("Réponse JSON invalide de l'agent pc_remote") from exc
            if attempt < self.device.retries:
                await asyncio.sleep(0.05 * (attempt + 1))
        raise PCRemoteUnavailable(f"PC distant '{self.device.id}' injoignable") from last_error

"""Client HTTP vers le service goal.

Remplace les imports directs `from goal.xxx import ...` que le core
utilisait quand goal tournait dans le même process. Toute erreur réseau
est convertie en GoalClientError plutôt que de laisser fuir une exception
httpx brute jusqu'à l'appelant.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from server.common.auth import api_key_headers
from server.common.http import async_client

logger = logging.getLogger("neron.goal_client")


class GoalClientError(RuntimeError):
    """Erreur générique d'appel au service goal (réseau, timeout, 5xx)."""


def _default_base_url() -> str:
    return os.getenv("NERON_GOAL_URL", "http://127.0.1.3:8030").rstrip("/")


def _default_api_key() -> str:
    return os.getenv("NERON_API_KEY", "").strip()


class GoalClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.api_key = api_key if api_key is not None else _default_api_key()
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return async_client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=api_key_headers(self.api_key),
            transport=self._transport,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | None:
        try:
            async with self._client() as client:
                response = await client.request(method, path, json=json, params=params)
        except httpx.TimeoutException as exc:
            raise GoalClientError(f"Timeout appelant goal {method} {path}") from exc
        except httpx.RequestError as exc:
            raise GoalClientError(f"Erreur réseau appelant goal {method} {path}: {exc}") from exc

        if response.status_code == 404 and allow_404:
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GoalClientError(
                f"goal {method} {path} -> {response.status_code}: {response.text[:200]}"
            ) from exc
        if not response.content:
            return {}
        return response.json()

    # ── Goals ──────────────────────────────────────────────────────────
    async def run_goal(self, objective: str, *, source: str = "api") -> dict[str, Any]:
        result = await self._request(
            "POST", "/goals/run", json={"objective": objective, "source": source}
        )
        assert result is not None
        return result

    async def queue_goal(self, objective: str, *, source: str = "api") -> dict[str, Any]:
        result = await self._request(
            "POST", "/goal", json={"objective": objective, "source": source}
        )
        assert result is not None
        return result

    async def get_active_goal(self) -> dict[str, Any] | None:
        result = await self._request("GET", "/goals/active")
        return (result or {}).get("active_goal")

    async def get_goal_status(self, goal_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/goal/{goal_id}/status", allow_404=True)

    # ── Projects ───────────────────────────────────────────────────────
    async def list_projects(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        result = await self._request("GET", "/projects", params=params)
        return (result or {}).get("projects", [])

    async def search_projects(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        result = await self._request("GET", "/projects/search", params={"q": query, "limit": limit})
        return (result or {}).get("projects", [])

    # ── Tasks ──────────────────────────────────────────────────────────
    async def get_task_summary(self) -> dict[str, Any]:
        result = await self._request("GET", "/tasks/summary")
        assert result is not None
        return result

    async def get_next_task(self) -> dict[str, Any] | None:
        result = await self._request("GET", "/tasks/next", allow_404=True)
        return (result or {}).get("task") if result else None

    async def start_next_task(self) -> dict[str, Any] | None:
        result = await self._request("POST", "/tasks/next/start", allow_404=True)
        return (result or {}).get("task") if result else None

    # ── Agents ─────────────────────────────────────────────────────────
    # Le registre d'agents et leurs fichiers vivent côté Goal, éventuellement
    # sur une autre machine : le Core ne les touche qu'à travers ces routes.

    async def list_agents(self) -> dict[str, Any]:
        """{"count", "agents": [noms], "disabled": [noms]} (disabled : Goal récent)."""
        result = await self._request("GET", "/agents")
        assert result is not None
        return result

    async def set_agent_enabled(self, agent_name: str, enabled: bool) -> dict[str, Any]:
        action = "enable" if enabled else "disable"
        result = await self._request("POST", f"/agents/{quote(agent_name, safe='')}/{action}")
        assert result is not None
        return result

    async def delete_agent(self, agent_name: str) -> dict[str, Any]:
        result = await self._request("POST", f"/agents/{quote(agent_name, safe='')}/delete")
        assert result is not None
        return result


_goal_client: GoalClient | None = None


def get_goal_client() -> GoalClient:
    global _goal_client
    if _goal_client is None:
        _goal_client = GoalClient()
    return _goal_client

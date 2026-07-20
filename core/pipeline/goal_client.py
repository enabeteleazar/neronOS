"""Client HTTP du core vers le service goal (phase 3).

Remplace TOUS les imports directs `from goal.…` du core. La frontière
de service est le réseau : http://<goal>:8030, clé API Bearer.

Résolution de l'URL : NERON_GOAL_URL > neron.server.yaml (nodes.goal)
> défaut 127.0.1.3:8030.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("core.goal_client")

_DEFAULT_TIMEOUT = 10.0
_RUN_TIMEOUT = 300.0  # run_goal est synchrone côté goal et peut être long


def _goal_base_url() -> str:
    url = os.getenv("NERON_GOAL_URL", "").strip()
    if url:
        return url.rstrip("/")
    root = Path(os.getenv("NERON_ROOT", "/etc/neronOS"))
    config = Path(os.getenv("NERON_SERVER_CONFIG", str(root / "neron.server.yaml")))
    try:
        import yaml

        nodes = (yaml.safe_load(config.read_text(encoding="utf-8")) or {}).get("nodes") or {}
        node = nodes.get("goal") or {}
        if node.get("host"):
            return f"http://{node['host']}:{node.get('port', 8030)}"
    except Exception as exc:
        logger.warning("Topologie goal illisible (%s) : %s", config, exc)
    return "http://127.0.1.3:8030"


def _headers() -> dict[str, str]:
    key = os.getenv("NERON_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


class GoalServiceError(RuntimeError):
    """Le service goal est injoignable ou a répondu en erreur."""


class GoalService:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or _goal_base_url()).rstrip("/")

    # ── transport ──────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        allow_404: bool = False,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=_headers(),
                timeout=timeout,
            ) as client:
                response = await client.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise GoalServiceError(
                f"Service goal injoignable ({self.base_url}{path}) : {exc}"
            ) from exc
        if allow_404 and response.status_code == 404:
            return None
        if response.is_error:
            raise GoalServiceError(
                f"Service goal HTTP {response.status_code} sur {path} : "
                f"{response.text[:200]}"
            )
        return response.json()

    def _request_sync(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Any:
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers=_headers(),
                timeout=timeout,
            ) as client:
                response = client.request(method, path, params=params)
        except httpx.HTTPError as exc:
            raise GoalServiceError(
                f"Service goal injoignable ({self.base_url}{path}) : {exc}"
            ) from exc
        if response.is_error:
            raise GoalServiceError(
                f"Service goal HTTP {response.status_code} sur {path}"
            )
        return response.json()

    # ── objectifs ──────────────────────────────────────────────────
    async def run_goal(self, objective: str, *, source: str = "api") -> dict[str, Any]:
        return await self._request(
            "POST",
            "/goals/run",
            json={"objective": objective, "source": source},
            timeout=_RUN_TIMEOUT,
        )

    async def queue_goal(self, objective: str, *, source: str = "api") -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/goal",
            json={"objective": objective, "source": source},
        )
        # Forme "goal" attendue par les appelants historiques de queue_goal
        return {
            "id": data.get("goal_id"),
            "title": objective,
            "status": data.get("status", "queued"),
            "metadata": {},
            "accepted": data.get("accepted", True),
            "status_url": data.get("status_url"),
        }

    async def get_active_goal(self) -> dict[str, Any] | None:
        data = await self._request("GET", "/goals/active")
        return data.get("active_goal")

    async def get_goal_status(self, goal_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/goal/{goal_id}/status", allow_404=True)

    # ── tâches ─────────────────────────────────────────────────────
    async def task_summary(self) -> dict[str, Any]:
        return await self._request("GET", "/tasks/summary")

    async def next_task(self) -> dict[str, Any] | None:
        data = await self._request("GET", "/tasks/next")
        return data.get("task")

    async def start_next_task(self) -> dict[str, Any] | None:
        data = await self._request("POST", "/tasks/next/start")
        return data.get("task")

    # ── projets ────────────────────────────────────────────────────
    async def find_projects(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "/projects/search", params={"query": query, "limit": limit}
        )
        return list(data.get("projects") or [])

    def list_projects_sync(self, limit: int = 20) -> list[dict[str, Any]]:
        data = self._request_sync("GET", "/projects", params={"limit": limit})
        return list(data.get("projects") or [])


_service: GoalService | None = None


def get_goal_service() -> GoalService:
    global _service
    if _service is None:
        _service = GoalService()
    return _service

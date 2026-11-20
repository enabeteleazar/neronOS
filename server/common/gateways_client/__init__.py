"""Client HTTP vers le service gateways (registre de passerelles).

Remplace les imports directs `from gateways.xxx import ...` du résolveur de
capacités : depuis le retrait des sous-modules (16/10), le paquet gateways
n'est plus livré avec neronOS, et chaque module doit pouvoir tourner sur son
propre serveur. Les jetons OAuth (Google…) restent sur la machine de
Gateways : toute action qui en a besoin s'y exécute.

Adresse : NERON_GATEWAYS_URL, sinon le nœud `gateways` de neron.server.yaml
(seule source de vérité de la topologie), sinon http://127.0.1.8:8070.
Authentification : en-tête X-Gateways-Key = NERON_GATEWAYS_API_KEY.

Toute erreur réseau, d'authentification ou 5xx devient GatewaysUnavailable :
l'appelant doit pouvoir distinguer « Gateways injoignable » de « aucune
passerelle pour ce domaine ».
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("neron.gateways_client")

DEFAULT_BASE_URL = "http://127.0.1.8:8070"
LOOKUP_TIMEOUT = 3.0
ACTION_TIMEOUT = 20.0


class GatewaysUnavailable(RuntimeError):
    """Service gateways injoignable, non authentifié ou en erreur."""


class GatewayActionFailed(RuntimeError):
    """Gateways a répondu mais l'action a échoué (ex. Google non connecté)."""


@dataclass(frozen=True)
class GatewayConnector:
    id: str
    name: str
    connect_hint: str = ""
    domains: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class GatewayState:
    status: str
    detail: str | None = None


def _base_url() -> str:
    env = os.getenv("NERON_GATEWAYS_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        import yaml

        from server.common.paths import NERON_ROOT

        plan = Path(os.getenv("NERON_SERVER_CONFIG", str(NERON_ROOT / "neron.server.yaml")))
        node = ((yaml.safe_load(plan.read_text(encoding="utf-8")) or {}).get("nodes") or {}).get("gateways")
        if isinstance(node, dict) and node.get("host") and node.get("port"):
            return f"http://{node['host']}:{int(node['port'])}"
    except Exception as exc:
        logger.debug("gateways_url_from_topology_failed %s", exc)
    return DEFAULT_BASE_URL


def _headers() -> dict[str, str]:
    key = os.getenv("NERON_GATEWAYS_API_KEY", "").strip()
    return {"X-Gateways-Key": key} if key else {}


def _connector(view: dict[str, Any]) -> tuple[GatewayConnector, GatewayState]:
    connector = view.get("connector") or {}
    state = view.get("state") or {}
    return (
        GatewayConnector(
            id=str(connector.get("id") or ""),
            name=str(connector.get("name") or connector.get("id") or ""),
            connect_hint=str(connector.get("connect_hint") or ""),
            domains=tuple(connector.get("domains") or ()),
            raw=connector,
        ),
        GatewayState(status=str(state.get("status") or "unknown"), detail=state.get("detail")),
    )


def _check(response: httpx.Response, what: str) -> None:
    if response.status_code in (401, 403) or response.status_code >= 500:
        raise GatewaysUnavailable(f"gateways {what} -> {response.status_code}: {response.text[:200]}")


class GatewaysClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or _base_url()).rstrip("/")
        self._transport = transport
        self._async_transport = async_transport

    def _get(self, path: str, timeout: float) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self.base_url, headers=_headers(), timeout=timeout, transport=self._transport
            ) as client:
                return client.get(path)
        except httpx.HTTPError as exc:
            raise GatewaysUnavailable(f"gateways GET {path}: {exc}") from exc

    def find_by_domain(self, domain: str) -> list[tuple[GatewayConnector, GatewayState]]:
        path = f"/gateways/domain/{quote(domain, safe='')}"
        response = self._get(path, LOOKUP_TIMEOUT)
        _check(response, path)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [_connector(view) for view in response.json().get("connectors") or []]

    def get_connector(self, connector_id: str) -> GatewayConnector | None:
        path = f"/gateways/{quote(connector_id, safe='')}"
        response = self._get(path, LOOKUP_TIMEOUT)
        _check(response, path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _connector(response.json())[0]

    async def google_calendar_upcoming(self, max_results: int = 5) -> dict[str, Any]:
        """{"events": [...], "text": "..."} ; l'appel Google se fait sur la
        machine de Gateways, qui détient le jeton OAuth."""
        path = "/gateways/google/calendar/upcoming"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=_headers(),
                timeout=ACTION_TIMEOUT,
                transport=self._async_transport,
            ) as client:
                response = await client.get(path, params={"max_results": max_results})
        except httpx.HTTPError as exc:
            raise GatewaysUnavailable(f"gateways GET {path}: {exc}") from exc
        _check(response, path)
        if response.status_code == 409:
            raise GatewayActionFailed(str(response.json().get("detail") or "action refusée"))
        response.raise_for_status()
        return response.json()


def get_gateways_client() -> GatewaysClient:
    """Nouveau client à chaque appel : l'adresse est relue (topologie)."""
    return GatewaysClient()

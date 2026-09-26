from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from common.paths import service_version
from common.service import create_service_app
from gateways.auth import require_api_key
from gateways.models import ConnectorState, ConnectorView, DomainLookupResponse
from gateways.registry import ConnectorRegistry, get_registry
from gateways.store import ConnectionStore

VERSION = service_version(__file__)

_store = ConnectionStore()


def _view(connector) -> ConnectorView:
    # Lookup dynamique du global (jamais capture en defaut d'argument) : les
    # tests remplacent `gateways.app._store` par une instance isolee.
    return ConnectorView(connector=connector, state=_store.get_state(connector.id))


async def _health_details(request: Request) -> dict[str, Any]:
    return {"connectors": len(get_registry().list_connectors())}


app = create_service_app(
    name="gateways",
    title="Neron Gateways Service",
    version=VERSION,
    capabilities=["gateway-discovery", "gateway-connection-state"],
    health=_health_details,
)


def _registry() -> ConnectorRegistry:
    return get_registry()


@app.get(
    "/gateways",
    response_model=list[ConnectorView],
    dependencies=[Depends(require_api_key)],
)
def list_gateways() -> list[ConnectorView]:
    return [_view(c) for c in _registry().list_connectors()]


@app.get(
    "/gateways/domain/{domain}",
    response_model=DomainLookupResponse,
    dependencies=[Depends(require_api_key)],
)
def gateways_for_domain(domain: str) -> DomainLookupResponse:
    connectors = _registry().find_by_domain(domain)
    return DomainLookupResponse(domain=domain, connectors=[_view(c) for c in connectors])


@app.get(
    "/gateways/{connector_id}",
    response_model=ConnectorView,
    dependencies=[Depends(require_api_key)],
)
def get_gateway(connector_id: str) -> ConnectorView:
    connector = _registry().get(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Connecteur inconnu : {connector_id}")
    return _view(connector)


@app.post(
    "/gateways/{connector_id}/connect",
    response_model=ConnectorState,
    dependencies=[Depends(require_api_key)],
)
def connect_gateway(connector_id: str) -> ConnectorState:
    connector = _registry().get(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Connecteur inconnu : {connector_id}")

    missing = [name for name in connector.credential_env if not os.getenv(name)]
    if missing:
        _store.set_state(
            connector_id,
            "configured_disconnected",
            detail=f"Variables manquantes dans secrets.env : {', '.join(missing)}",
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Connexion impossible, variable(s) absente(s) de secrets.env : "
                f"{', '.join(missing)}. {connector.connect_hint}"
            ),
        )
    return _store.set_state(connector_id, "connected")


@app.post(
    "/gateways/{connector_id}/disconnect",
    response_model=ConnectorState,
    dependencies=[Depends(require_api_key)],
)
def disconnect_gateway(connector_id: str) -> ConnectorState:
    connector = _registry().get(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Connecteur inconnu : {connector_id}")
    return _store.set_state(connector_id, "configured_disconnected")

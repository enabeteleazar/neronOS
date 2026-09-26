from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from common.paths import service_version
from common.service import create_service_app
from gateways.auth import require_api_key
from gateways.models import (
    ConnectorState,
    ConnectorView,
    DeviceAuthorizationResponse,
    DomainLookupResponse,
    OAuthPollResponse,
)
from gateways.providers.google_auth import GoogleAuthClient, GoogleAuthError
from gateways.registry import ConnectorRegistry, get_registry
from gateways.store import ConnectionStore
from gateways.token_store import TokenStore

VERSION = service_version(__file__)

_store = ConnectionStore()
_token_store = TokenStore()

# Device flow en cours par connecteur : {connector_id: device_code}. En
# memoire (pas de multi-instance ici) — un device_code expire au bout de
# ~30 min cote Google, perdre l'etat au redemarrage n'est jamais grave.
_pending_device_flows: dict[str, str] = {}


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

    if connector_id == "google":
        raise HTTPException(
            status_code=409,
            detail=(
                "Google utilise le flux OAuth device : "
                "POST /gateways/google/oauth/start puis /gateways/google/oauth/poll."
            ),
        )

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
    _token_store.delete(connector_id)
    _pending_device_flows.pop(connector_id, None)
    return _store.set_state(connector_id, "configured_disconnected")


def _google_auth_client() -> GoogleAuthClient:
    client_id = os.getenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=409,
            detail=(
                "NERON_GATEWAY_GOOGLE_CLIENT_ID / NERON_GATEWAY_GOOGLE_CLIENT_SECRET "
                "absents de secrets.env."
            ),
        )
    return GoogleAuthClient(client_id=client_id, client_secret=client_secret)


@app.post(
    "/gateways/google/oauth/start",
    response_model=DeviceAuthorizationResponse,
    dependencies=[Depends(require_api_key)],
)
def start_google_oauth() -> DeviceAuthorizationResponse:
    auth = _google_auth_client()
    try:
        authorization = auth.start_device_authorization()
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _pending_device_flows["google"] = authorization.device_code
    _store.set_state(
        "google",
        "configured_disconnected",
        detail=f"En attente de validation sur {authorization.verification_url}",
    )
    return DeviceAuthorizationResponse(
        user_code=authorization.user_code,
        verification_url=authorization.verification_url,
        expires_in=authorization.expires_in,
        interval=authorization.interval,
    )


@app.post(
    "/gateways/google/oauth/poll",
    response_model=OAuthPollResponse,
    dependencies=[Depends(require_api_key)],
)
def poll_google_oauth() -> OAuthPollResponse:
    device_code = _pending_device_flows.get("google")
    if device_code is None:
        raise HTTPException(
            status_code=409,
            detail="Aucun flux OAuth Google en cours. Lance POST /gateways/google/oauth/start.",
        )

    auth = _google_auth_client()
    try:
        token = auth.poll_device_token(device_code)
    except GoogleAuthError as exc:
        _pending_device_flows.pop("google", None)
        _store.set_state("google", "error", detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if token is None:
        return OAuthPollResponse(status="pending")

    if not token.refresh_token:
        _pending_device_flows.pop("google", None)
        _store.set_state(
            "google",
            "error",
            detail="Google n'a pas renvoye de refresh_token (revoque l'acces et reessaie).",
        )
        raise HTTPException(
            status_code=502,
            detail="Google n'a pas renvoye de refresh_token. Revoque l'acces existant dans "
            "ton compte Google puis relance /gateways/google/oauth/start.",
        )

    _token_store.set_refresh_token("google", token.refresh_token)
    _pending_device_flows.pop("google", None)
    _store.set_state("google", "connected")
    return OAuthPollResponse(status="connected")

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Protocol = Literal["rest", "mcp", "caldav_carddav"]
AuthType = Literal["oauth2", "app_password"]
ConnectionStatus = Literal[
    "not_configured", "configured_disconnected", "connected", "error"
]


class Connector(BaseModel):
    id: str
    name: str
    domains: list[str]
    protocol: Protocol
    auth_type: AuthType
    credential_env: list[str] = []
    connect_hint: str = ""


class ConnectorState(BaseModel):
    connector_id: str
    status: ConnectionStatus
    detail: str | None = None
    updated_at: str


class ConnectorView(BaseModel):
    connector: Connector
    state: ConnectorState


class DomainLookupResponse(BaseModel):
    domain: str
    connectors: list[ConnectorView]


class DeviceAuthorizationResponse(BaseModel):
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


OAuthPollStatus = Literal["pending", "connected", "error"]


class OAuthPollResponse(BaseModel):
    status: OAuthPollStatus
    detail: str | None = None

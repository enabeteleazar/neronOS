from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from gateways import app as gateways_app
from gateways.config import cfg
from gateways.providers.google_auth import GoogleAuthClient
from gateways.store import ConnectionStore
from gateways.token_store import TokenStore

API_KEY = "test-gateways-key"
HEADERS = {"X-Gateways-Key": API_KEY}


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cfg, "API_KEY", API_KEY)
    monkeypatch.setattr(cfg, "AUTH_DEV_MODE", False)
    monkeypatch.setattr(
        gateways_app, "_store", ConnectionStore(path=tmp_path / "gateways.sqlite3")
    )
    monkeypatch.setattr(
        gateways_app, "_token_store", TokenStore(path=tmp_path / "tokens.sqlite3")
    )
    monkeypatch.setattr(gateways_app, "_pending_device_flows", {})
    gateways_app.app.state.started_at = time.monotonic()
    gateways_app.app.state.registry_client = None
    return tmp_path


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateways_app.app),
        base_url="http://gateways.test",
    )


def _fake_auth_client(handler) -> GoogleAuthClient:
    return GoogleAuthClient(
        client_id="cid", client_secret="csecret", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_oauth_start_without_client_credentials_is_409(configured, monkeypatch):
    monkeypatch.delenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", raising=False)
    async with _client() as client:
        response = await client.post("/gateways/google/oauth/start", headers=HEADERS)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_oauth_start_returns_user_code_and_marks_pending(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "csecret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_code": "devcode123",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://www.google.com/device",
                "expires_in": 1800,
                "interval": 5,
            },
        )

    monkeypatch.setattr(gateways_app, "_google_auth_client", lambda: _fake_auth_client(handler))

    async with _client() as client:
        response = await client.post("/gateways/google/oauth/start", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["user_code"] == "ABCD-EFGH"

    async with _client() as client:
        state = await client.get("/gateways/google", headers=HEADERS)
    assert state.json()["state"]["status"] == "configured_disconnected"


@pytest.mark.asyncio
async def test_oauth_poll_without_pending_flow_is_409(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "csecret")
    async with _client() as client:
        response = await client.post("/gateways/google/oauth/poll", headers=HEADERS)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_oauth_poll_returns_pending_while_user_has_not_validated(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "csecret")
    gateways_app._pending_device_flows["google"] = "devcode123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "authorization_pending"})

    monkeypatch.setattr(gateways_app, "_google_auth_client", lambda: _fake_auth_client(handler))

    async with _client() as client:
        response = await client.post("/gateways/google/oauth/poll", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_oauth_poll_stores_refresh_token_and_marks_connected(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "csecret")
    gateways_app._pending_device_flows["google"] = "devcode123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        )

    monkeypatch.setattr(gateways_app, "_google_auth_client", lambda: _fake_auth_client(handler))

    async with _client() as client:
        response = await client.post("/gateways/google/oauth/poll", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert gateways_app._token_store.get_refresh_token("google") == "rt-1"
    assert "google" not in gateways_app._pending_device_flows

    async with _client() as client:
        state = await client.get("/gateways/google", headers=HEADERS)
    assert state.json()["state"]["status"] == "connected"


@pytest.mark.asyncio
async def test_oauth_poll_without_refresh_token_is_rejected(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "csecret")
    gateways_app._pending_device_flows["google"] = "devcode123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})

    monkeypatch.setattr(gateways_app, "_google_auth_client", lambda: _fake_auth_client(handler))

    async with _client() as client:
        response = await client.post("/gateways/google/oauth/poll", headers=HEADERS)
    assert response.status_code == 502
    assert gateways_app._token_store.get_refresh_token("google") is None


@pytest.mark.asyncio
async def test_generic_connect_endpoint_rejects_google(configured):
    async with _client() as client:
        response = await client.post("/gateways/google/connect", headers=HEADERS)
    assert response.status_code == 409
    assert "oauth/start" in response.json()["detail"]


@pytest.mark.asyncio
async def test_disconnect_clears_stored_refresh_token(configured):
    gateways_app._token_store.set_refresh_token("google", "rt-1")
    async with _client() as client:
        response = await client.post("/gateways/google/disconnect", headers=HEADERS)
    assert response.status_code == 200
    assert gateways_app._token_store.get_refresh_token("google") is None

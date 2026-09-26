from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from gateways import app as gateways_app
from gateways.config import cfg
from gateways.store import ConnectionStore

API_KEY = "test-gateways-key"
HEADERS = {"X-Gateways-Key": API_KEY}


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cfg, "API_KEY", API_KEY)
    monkeypatch.setattr(cfg, "AUTH_DEV_MODE", False)
    monkeypatch.setattr(
        gateways_app, "_store", ConnectionStore(path=tmp_path / "gateways.sqlite3")
    )
    # Le lifespan (qui pose started_at / registry_client) ne tourne pas sous
    # ASGITransport nu : on reproduit son minimum pour /health.
    gateways_app.app.state.started_at = time.monotonic()
    gateways_app.app.state.registry_client = None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateways_app.app),
        base_url="http://gateways.test",
    )


@pytest.mark.asyncio
async def test_health_does_not_require_auth(configured):
    async with _client() as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "gateways"


@pytest.mark.asyncio
async def test_list_gateways_requires_api_key(configured):
    async with _client() as client:
        response = await client.get("/gateways")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_gateways_returns_all_connectors_not_configured_by_default(configured):
    async with _client() as client:
        response = await client.get("/gateways", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert {item["connector"]["id"] for item in payload} == {
        "google", "microsoft", "apple", "github", "notion",
    }
    assert all(item["state"]["status"] == "not_configured" for item in payload)


@pytest.mark.asyncio
async def test_domain_lookup_returns_matching_connectors(configured):
    async with _client() as client:
        response = await client.get("/gateways/domain/repos", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == "repos"
    assert [c["connector"]["id"] for c in payload["connectors"]] == ["github"]


@pytest.mark.asyncio
async def test_domain_lookup_returns_empty_list_when_no_gateway_covers_it(configured):
    async with _client() as client:
        response = await client.get("/gateways/domain/does-not-exist", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["connectors"] == []


@pytest.mark.asyncio
async def test_get_unknown_gateway_is_404(configured):
    async with _client() as client:
        response = await client.get("/gateways/does-not-exist", headers=HEADERS)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_connect_without_credentials_returns_409_with_hint(configured, monkeypatch):
    monkeypatch.delenv("NERON_GATEWAY_GITHUB_TOKEN", raising=False)
    async with _client() as client:
        response = await client.post("/gateways/github/connect", headers=HEADERS)
    assert response.status_code == 409
    assert "NERON_GATEWAY_GITHUB_TOKEN" in response.json()["detail"]

    async with _client() as client:
        state = await client.get("/gateways/github", headers=HEADERS)
    assert state.json()["state"]["status"] == "configured_disconnected"


@pytest.mark.asyncio
async def test_connect_with_credentials_present_marks_connected(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GITHUB_TOKEN", "fake-token-for-tests")
    async with _client() as client:
        response = await client.post("/gateways/github/connect", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


@pytest.mark.asyncio
async def test_disconnect_resets_state(configured, monkeypatch):
    monkeypatch.setenv("NERON_GATEWAY_GITHUB_TOKEN", "fake-token-for-tests")
    async with _client() as client:
        await client.post("/gateways/github/connect", headers=HEADERS)
        response = await client.post("/gateways/github/disconnect", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "configured_disconnected"

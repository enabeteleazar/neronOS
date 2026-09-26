from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gateways.actions import (
    GatewayActionError,
    fetch_upcoming_calendar_events,
    format_events_for_response,
)
from gateways.providers.google_auth import GoogleAuthClient
from gateways.token_store import TokenStore


def _token_store(tmp_path: Path, refresh_token: str | None = "rt-existing") -> TokenStore:
    store = TokenStore(path=tmp_path / "tokens.sqlite3")
    if refresh_token:
        store.set_refresh_token("google", refresh_token)
    return store


def _auth_client(handler) -> GoogleAuthClient:
    return GoogleAuthClient(
        client_id="cid", client_secret="csecret", transport=httpx.MockTransport(handler)
    )


def test_fetch_raises_when_google_is_not_connected(tmp_path: Path):
    store = _token_store(tmp_path, refresh_token=None)

    with pytest.raises(GatewayActionError, match="pas connecte"):
        fetch_upcoming_calendar_events(token_store=store, auth_client=_auth_client(lambda r: httpx.Response(200)))


def test_fetch_refreshes_token_then_lists_events(tmp_path: Path):
    store = _token_store(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        return httpx.Response(200, json={"items": [{"summary": "Standup"}]})

    events = fetch_upcoming_calendar_events(
        token_store=store,
        auth_client=_auth_client(handler),
        calendar_transport=httpx.MockTransport(handler),
    )

    assert [e["summary"] for e in events] == ["Standup"]


def test_fetch_updates_stored_refresh_token_when_google_reissues_one(tmp_path: Path):
    store = _token_store(tmp_path, refresh_token="rt-old")

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com" in str(request.url):
            return httpx.Response(
                200,
                json={"access_token": "at-1", "refresh_token": "rt-new", "expires_in": 3600},
            )
        return httpx.Response(200, json={"items": []})

    fetch_upcoming_calendar_events(
        token_store=store,
        auth_client=_auth_client(handler),
        calendar_transport=httpx.MockTransport(handler),
    )

    assert store.get_refresh_token("google") == "rt-new"


def test_fetch_wraps_auth_errors_as_gateway_action_error(tmp_path: Path):
    store = _token_store(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(GatewayActionError):
        fetch_upcoming_calendar_events(token_store=store, auth_client=_auth_client(handler))


def test_format_events_for_response_with_no_events():
    assert "Aucun événement" in format_events_for_response([])


def test_format_events_for_response_lists_summary_and_start():
    events = [
        {"summary": "Reunion equipe", "start": {"dateTime": "2026-09-26T10:00:00Z"}},
        {"start": {"date": "2026-09-27"}},
    ]
    text = format_events_for_response(events)
    assert "Reunion equipe" in text
    assert "2026-09-26T10:00:00Z" in text
    assert "(sans titre)" in text
    assert "2026-09-27" in text

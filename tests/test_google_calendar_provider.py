from __future__ import annotations

import httpx
import pytest

from gateways.providers.google_calendar import (
    EVENTS_URL,
    GoogleCalendarError,
    list_upcoming_events,
)


def test_list_upcoming_events_sends_bearer_token_and_parses_items():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(EVENTS_URL)
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            json={"items": [{"summary": "Reunion"}, {"summary": "Dentiste"}]},
        )

    events = list_upcoming_events("tok-123", transport=httpx.MockTransport(handler))

    assert [e["summary"] for e in events] == ["Reunion", "Dentiste"]
    assert seen_headers["authorization"] == "Bearer tok-123"


def test_list_upcoming_events_returns_empty_list_when_no_items():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert list_upcoming_events("tok-123", transport=httpx.MockTransport(handler)) == []


def test_list_upcoming_events_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(GoogleCalendarError):
        list_upcoming_events("expired-token", transport=httpx.MockTransport(handler))

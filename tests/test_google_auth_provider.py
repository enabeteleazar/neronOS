from __future__ import annotations

import httpx
import pytest

from gateways.providers.google_auth import (
    DEVICE_CODE_URL,
    TOKEN_URL,
    GoogleAuthClient,
    GoogleAuthError,
)


def _client(handler) -> GoogleAuthClient:
    return GoogleAuthClient(
        client_id="cid",
        client_secret="csecret",
        transport=httpx.MockTransport(handler),
    )


def test_start_device_authorization_returns_parsed_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DEVICE_CODE_URL
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

    authorization = _client(handler).start_device_authorization()

    assert authorization.device_code == "devcode123"
    assert authorization.user_code == "ABCD-EFGH"
    assert authorization.verification_url == "https://www.google.com/device"
    assert authorization.interval == 5


def test_start_device_authorization_raises_on_error_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_client"})

    with pytest.raises(GoogleAuthError):
        _client(handler).start_device_authorization()


def test_poll_device_token_returns_none_while_pending():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        return httpx.Response(400, json={"error": "authorization_pending"})

    assert _client(handler).poll_device_token("devcode123") is None


def test_poll_device_token_returns_none_on_slow_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "slow_down"})

    assert _client(handler).poll_device_token("devcode123") is None


def test_poll_device_token_raises_on_denied_access():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "access_denied"})

    with pytest.raises(GoogleAuthError):
        _client(handler).poll_device_token("devcode123")


def test_poll_device_token_returns_result_once_approved():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "at-123",
                "refresh_token": "rt-456",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    token = _client(handler).poll_device_token("devcode123")

    assert token is not None
    assert token.access_token == "at-123"
    assert token.refresh_token == "rt-456"


def test_refresh_access_token_keeps_old_refresh_token_when_not_reissued():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at-789", "expires_in": 3600})

    token = _client(handler).refresh_access_token("rt-existing")

    assert token.access_token == "at-789"
    assert token.refresh_token == "rt-existing"


def test_refresh_access_token_raises_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(GoogleAuthError):
        _client(handler).refresh_access_token("rt-existing")

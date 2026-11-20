from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from integrations.pc_remote import config as pc_remote_config
from integrations.pc_remote.client import PCRemoteClient
from integrations.pc_remote.config import PCRemoteDevice, is_enabled, load_devices
from integrations.pc_remote.errors import (
    PCRemoteAuthError,
    PCRemoteDeviceNotFound,
    PCRemoteUnavailable,
)
from integrations.pc_remote.service import PCRemoteService
from integrations.pc_remote.tool import execute, tool_spec


def _device(**overrides) -> PCRemoteDevice:
    base = dict(
        id="pc_windows_bureau",
        name="PC Windows bureau",
        url="http://100.64.0.1:8765",
        token="tok-secret",
        timeout=1.0,
        retries=0,
    )
    base.update(overrides)
    return PCRemoteDevice(**base)


def test_tool_spec_never_allows_system_commands():
    """Regression : ce tool ne doit jamais reclasser en execution locale.

    L'agent pc_remote n'execute rien dans le process Neron, seulement un
    appel reseau vers une machine deja controlee (meme logique que le tool
    homeassistant) : la ligne suivante doit rester False, sinon ToolRuntime
    rejette le tool avec `unsafe_tool_rejected`.
    """
    spec = tool_spec()
    assert spec.safety["allow_system_commands"] is False
    assert spec.safety["requires_network"] is True


@pytest.mark.asyncio
async def test_client_open_app_sends_bearer_token_and_correct_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["method"] = request.method
        return httpx.Response(200, json={"status": "opened"})

    client = PCRemoteClient(_device(), transport=httpx.MockTransport(handler))
    result = await client.open_app("chrome")

    assert result == {"status": "opened"}
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/apps/chrome/open")
    assert seen["headers"]["authorization"] == "Bearer tok-secret"


@pytest.mark.asyncio
async def test_client_raises_auth_error_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = PCRemoteClient(_device(), transport=httpx.MockTransport(handler))

    with pytest.raises(PCRemoteAuthError):
        await client.close_app("chrome")


@pytest.mark.asyncio
async def test_client_raises_unavailable_when_not_configured():
    client = PCRemoteClient(_device(token=""))

    with pytest.raises(PCRemoteUnavailable):
        await client.list_apps()


@pytest.mark.asyncio
async def test_service_raises_device_not_found_for_unknown_id():
    service = PCRemoteService(devices={})
    with pytest.raises(PCRemoteDeviceNotFound):
        await service.open_app("unknown_device", "chrome")


@pytest.mark.asyncio
async def test_tool_execute_open_delegates_to_service(monkeypatch):
    fake_service = AsyncMock()
    fake_service.open_app.return_value = {"status": "opened"}
    monkeypatch.setattr(
        "integrations.pc_remote.tool.get_pc_remote_service",
        lambda: fake_service,
    )

    result = await execute({"action": "open", "device_id": "pc_windows_bureau", "app_id": "chrome"})

    assert result.ok is True
    fake_service.open_app.assert_awaited_once_with("pc_windows_bureau", "chrome")


@pytest.mark.asyncio
async def test_tool_execute_maps_domain_error_to_failed_result(monkeypatch):
    fake_service = AsyncMock()
    fake_service.open_app.side_effect = PCRemoteDeviceNotFound("PC distant inconnu : x")
    monkeypatch.setattr(
        "integrations.pc_remote.tool.get_pc_remote_service",
        lambda: fake_service,
    )

    result = await execute({"action": "open", "device_id": "x", "app_id": "chrome"})

    assert result.ok is False
    assert result.error == PCRemoteDeviceNotFound.user_message


@pytest.mark.asyncio
async def test_tool_execute_rejects_unsupported_action():
    result = await execute({"action": "reboot", "device_id": "pc_windows_bureau"})
    assert result.ok is False
    assert result.error == "unsupported_action:reboot"


def test_is_enabled_defaults_true_when_key_absent(monkeypatch):
    monkeypatch.setattr(pc_remote_config, "_project_config", lambda: {"pc_remote": {"devices": []}})
    assert is_enabled() is True


def test_is_enabled_reflects_explicit_false(monkeypatch):
    monkeypatch.setattr(
        pc_remote_config, "_project_config", lambda: {"pc_remote": {"enabled": False, "devices": []}}
    )
    assert is_enabled() is False


def test_load_devices_returns_empty_registry_when_disabled(monkeypatch):
    """Regression : `pc_remote.enabled: false` doit vider le registre, meme
    si des devices sont declares sous `devices` (flag auparavant jamais lu
    nulle part, donc sans aucun effet)."""
    monkeypatch.setattr(
        pc_remote_config,
        "_project_config",
        lambda: {
            "pc_remote": {
                "enabled": False,
                "devices": [{"id": "pc_windows", "url": "http://100.0.0.1:8765", "token_env": "X"}],
            }
        },
    )
    assert load_devices() == {}


def test_load_devices_loads_registry_when_enabled(monkeypatch):
    monkeypatch.setattr(pc_remote_config, "_secrets", lambda: {})
    monkeypatch.setenv("PC_REMOTE_PC_TEST_TOKEN", "tok")
    monkeypatch.setattr(
        pc_remote_config,
        "_project_config",
        lambda: {
            "pc_remote": {
                "enabled": True,
                "devices": [
                    {
                        "id": "pc_test",
                        "url": "http://100.0.0.1:8765",
                        "token_env": "PC_REMOTE_PC_TEST_TOKEN",
                    }
                ],
            }
        },
    )
    devices = load_devices()
    assert "pc_test" in devices
    assert devices["pc_test"].token == "tok"

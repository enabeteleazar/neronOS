from unittest.mock import AsyncMock, Mock

import pytest

from core.providers.models import ProviderRequest
from integrations.homeassistant.provider import HomeAssistantProvider


@pytest.mark.asyncio
async def test_homeassistant_provider_capabilities():
    provider = HomeAssistantProvider()

    assert provider.name == "homeassistant"
    assert "homeassistant.control" in provider.capabilities
    assert "homeassistant.state" in provider.capabilities


@pytest.mark.asyncio
async def test_homeassistant_provider_execute():
    service = Mock()
    service.config.enabled = True
    service.config.configured = True
    service.execute_natural = AsyncMock(
        return_value={"ok": True}
    )

    provider = HomeAssistantProvider(service=service)

    request = ProviderRequest(
        action="natural",
        payload={"text": "allume la lumière"},
        trace_id="test",
    )
    result = await provider.execute(request)

    assert result.status == "healthy"
    service.execute_natural.assert_awaited_once()

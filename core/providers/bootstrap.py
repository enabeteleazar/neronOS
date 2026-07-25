from __future__ import annotations

import logging

from .llm import ExternalLLMProvider
from .memory import ObliviaProvider
from .knowledge import ObsidianKnowledgeProvider
from .generic_wikipedia import WikipediaProvider
from .generic_web import WebProvider
from .registry import ProviderRegistry, provider_registry

logger = logging.getLogger("core.providers")


def ensure_default_providers(
    registry: ProviderRegistry = provider_registry,
) -> ProviderRegistry:
    """Register Kernel default providers idempotently."""

    if registry.get("oblivia") is None:
        registry.register(ObliviaProvider())
        logger.info("Provider registered: oblivia")

    if registry.get("obsidian-knowledge") is None:
        registry.register(ObsidianKnowledgeProvider())
        logger.info("Provider registered: obsidian-knowledge")

    if registry.get("wikipedia") is None:
        registry.register(WikipediaProvider())
        logger.info("Provider registered: wikipedia")

    if registry.get("web-search") is None:
        registry.register(WebProvider())
        logger.info("Provider registered: web-search")

    if registry.get("llm") is None:
        registry.register(ExternalLLMProvider())
        logger.info("Provider registered: llm")

    if registry.get("homeassistant") is None:
        from integrations.homeassistant.provider import HomeAssistantProvider

        registry.register(HomeAssistantProvider())
        logger.info("Provider registered: homeassistant")

    return registry

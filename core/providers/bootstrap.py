from __future__ import annotations

import logging

from .llm import LLMProvider
from .memory import ObliviaProvider
from .registry import ProviderRegistry, provider_registry

logger = logging.getLogger("core.providers")


def ensure_default_providers(
    registry: ProviderRegistry = provider_registry,
) -> ProviderRegistry:
    """Register Kernel default providers idempotently."""

    if registry.get("oblivia") is None:
        registry.register(ObliviaProvider())
        logger.info("Provider registered: oblivia")

    if registry.get("llm") is None:
        registry.register(LLMProvider())
        logger.info("Provider registered: llm")

    return registry

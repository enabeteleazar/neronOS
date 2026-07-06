from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ProviderInfo, ProviderRequest, ProviderResponse, ProviderStatus, ProviderType


class ProviderProtocol(ABC):
    """Common Kernel interface for capability providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def type(self) -> ProviderType:
        raise NotImplementedError

    @property
    @abstractmethod
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        raise NotImplementedError

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            type=self.type,
            status=self.status,
            capabilities=list(self.capabilities),
        )

    @abstractmethod
    async def health(self) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

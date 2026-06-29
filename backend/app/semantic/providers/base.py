from abc import ABC, abstractmethod

from backend.app.semantic.models import (
    ProviderBatchRequest,
    ProviderBatchResponse,
    ProviderMetadata,
)


class BaseAIProvider(ABC):
    """Provider-neutral interface for one multi-moment semantic request."""

    @property
    @abstractmethod
    def metadata(self) -> ProviderMetadata:
        """Describe the provider adapter, model, and batching limits."""

    @abstractmethod
    async def generate_batch(self, request: ProviderBatchRequest) -> ProviderBatchResponse:
        """Generate structured enrichment for every moment in one batch."""

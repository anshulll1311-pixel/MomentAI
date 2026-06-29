from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from backend.app.semantic.models import (
    ProviderBatchRequest,
    ProviderBatchResponse,
    ProviderFinishReason,
    ProviderMetadata,
    ProviderTokenUsage,
)


@dataclass(frozen=True, slots=True)
class ProviderRequestDiagnostic:
    """Non-sensitive execution details emitted by a provider adapter."""

    request_id: str
    provider_id: str
    model_id: str
    status: str
    latency_ms: float
    provider_request_id: str | None = None
    token_usage: ProviderTokenUsage = ProviderTokenUsage()
    finish_reason: ProviderFinishReason = ProviderFinishReason.UNKNOWN
    error_type: str | None = None
    retryable: bool = False


ProviderDiagnosticSink = Callable[[ProviderRequestDiagnostic], None]


class BaseAIProvider(ABC):
    """Provider-neutral interface for one multi-moment semantic request."""

    @property
    @abstractmethod
    def metadata(self) -> ProviderMetadata:
        """Describe the provider adapter, model, and batching limits."""

    def supports(self, capability: str) -> bool:
        """Report whether the provider advertises a named capability."""

        return capability in self.metadata.capabilities

    @abstractmethod
    async def generate_batch(self, request: ProviderBatchRequest) -> ProviderBatchResponse:
        """Generate structured enrichment for every moment in one batch."""

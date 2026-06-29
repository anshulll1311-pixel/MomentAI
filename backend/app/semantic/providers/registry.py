from collections.abc import Iterable

from backend.app.semantic.errors import ProviderNotFoundError, SemanticConfigurationError
from backend.app.semantic.models import ProviderMetadata
from backend.app.semantic.providers.base import BaseAIProvider


class ProviderRegistry:
    """Immutable registry of provider abstractions supplied by application composition."""

    def __init__(self, providers: Iterable[BaseAIProvider] = ()) -> None:
        ordered = tuple(providers)
        provider_ids = [provider.metadata.provider_id for provider in ordered]
        if len(provider_ids) != len(set(provider_ids)):
            raise SemanticConfigurationError("semantic provider IDs must be unique")
        self._ordered = ordered
        self._providers = {provider.metadata.provider_id: provider for provider in ordered}

    def resolve(self, provider_id: str) -> BaseAIProvider:
        if provider_id == "auto":
            if self._ordered:
                return self._ordered[0]
            raise ProviderNotFoundError("No semantic AI provider is registered.")
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise ProviderNotFoundError(
                f"Semantic AI provider is not registered: {provider_id}."
            ) from error

    def metadata(self) -> tuple[ProviderMetadata, ...]:
        return tuple(provider.metadata for provider in self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

from abc import ABC, abstractmethod
from typing import Mapping

from backend.app.semantic.models import SemanticCacheEntry


class SemanticCache(ABC):
    """Asynchronous cache port for independently addressable moment enrichments."""

    @abstractmethod
    async def get_many(self, keys: tuple[str, ...]) -> Mapping[str, SemanticCacheEntry]:
        """Return the subset of requested keys currently available."""

    @abstractmethod
    async def put_many(self, entries: tuple[SemanticCacheEntry, ...]) -> None:
        """Store validated moment enrichments."""

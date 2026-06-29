from typing import Mapping

from backend.app.semantic.caching.base import SemanticCache
from backend.app.semantic.models import SemanticCacheEntry


class NoOpSemanticCache(SemanticCache):
    """Default adapter that deliberately performs no persistence."""

    async def get_many(self, keys: tuple[str, ...]) -> Mapping[str, SemanticCacheEntry]:
        del keys
        return {}

    async def put_many(self, entries: tuple[SemanticCacheEntry, ...]) -> None:
        del entries

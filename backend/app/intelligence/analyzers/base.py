import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from backend.app.intelligence.models import (
    AnalysisContext,
    AnalyzerMetadata,
    MomentCandidate,
    SignalBatch,
)


class SignalAnalyzer(ABC):
    @property
    @abstractmethod
    def metadata(self) -> AnalyzerMetadata:
        """Return immutable identity, scheduling, dependency, and cost metadata."""

    @abstractmethod
    def cache_key(
        self,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
    ) -> str:
        """Return a deterministic cache key without reading or writing a cache."""

    @abstractmethod
    async def analyze(
        self,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
    ) -> SignalBatch:
        """Analyze candidates and return normalized signals."""


def deterministic_cache_key(analyzer: AnalyzerMetadata, payload: Any) -> str:
    serialized = json.dumps(
        {
            "analyzer_id": analyzer.analyzer_id,
            "version": analyzer.version,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

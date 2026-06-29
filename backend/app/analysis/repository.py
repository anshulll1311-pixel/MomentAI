"""Replaceable persistence boundary for immutable analysis results."""

from abc import ABC, abstractmethod
from datetime import datetime

from backend.app.analysis.models import (
    AnalysisArtifacts,
    AnalysisFailure,
    AnalysisRecord,
    ArtifactReference,
)
from backend.app.services.moment_pipeline_service import AnalysisResult


class AnalysisRepository(ABC):
    @abstractmethod
    async def create_pending(self, record: AnalysisRecord) -> AnalysisRecord:
        """Reserve an analysis ID and deduplication key."""

    @abstractmethod
    async def get(self, analysis_id: str) -> AnalysisRecord:
        """Retrieve one lifecycle record or raise AnalysisNotFoundError."""

    @abstractmethod
    async def find_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        """Find the current record for one versioned analysis key."""

    @abstractmethod
    async def mark_processing(self, analysis_id: str) -> AnalysisRecord:
        """Atomically transition a pending record to processing."""

    @abstractmethod
    async def save_result(
        self,
        analysis_id: str,
        result: AnalysisResult,
        artifacts: AnalysisArtifacts,
        completed_at: datetime,
    ) -> AnalysisRecord:
        """Publish one immutable result exactly once."""

    @abstractmethod
    async def mark_failed(
        self,
        analysis_id: str,
        failure: AnalysisFailure,
        failed_at: datetime,
    ) -> AnalysisRecord:
        """Record a sanitized pipeline failure."""

    @abstractmethod
    async def add_artifacts(
        self,
        analysis_id: str,
        references: tuple[ArtifactReference, ...],
    ) -> AnalysisRecord:
        """Attach derived artifact references without mutating AnalysisResult."""

    @abstractmethod
    async def expire(self, analysis_id: str, expired_at: datetime) -> AnalysisRecord:
        """Expire a record after its artifacts have been retired."""

"""Single-process development implementation of AnalysisRepository."""

import asyncio
from dataclasses import replace
from datetime import datetime

from backend.app.analysis.errors import AnalysisConflictError, AnalysisNotFoundError
from backend.app.analysis.models import (
    AnalysisArtifacts,
    AnalysisFailure,
    AnalysisRecord,
    AnalysisStatus,
    ArtifactReference,
)
from backend.app.analysis.repository import AnalysisRepository
from backend.app.services.moment_pipeline_service import AnalysisResult


class InMemoryAnalysisRepository(AnalysisRepository):
    """Concurrency-safe repository intended for one development process."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create_pending(self, record: AnalysisRecord) -> AnalysisRecord:
        if record.status is not AnalysisStatus.PENDING:
            raise AnalysisConflictError("new analysis record must be pending")
        async with self._lock:
            if record.analysis_id in self._records:
                raise AnalysisConflictError(f"analysis ID already exists: {record.analysis_id}")
            existing_id = self._keys.get(record.analysis_key)
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing.status not in (AnalysisStatus.FAILED, AnalysisStatus.EXPIRED):
                    raise AnalysisConflictError("analysis key is already active")
            self._records[record.analysis_id] = record
            self._keys[record.analysis_key] = record.analysis_id
            return record

    async def get(self, analysis_id: str) -> AnalysisRecord:
        async with self._lock:
            try:
                return self._records[analysis_id]
            except KeyError as error:
                raise AnalysisNotFoundError(f"Analysis was not found: {analysis_id}.") from error

    async def find_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        async with self._lock:
            analysis_id = self._keys.get(analysis_key)
            return self._records.get(analysis_id) if analysis_id is not None else None

    async def mark_processing(self, analysis_id: str) -> AnalysisRecord:
        async with self._lock:
            record = self._required(analysis_id)
            if record.status is not AnalysisStatus.PENDING:
                raise AnalysisConflictError("only pending analysis can start processing")
            updated = replace(
                record,
                status=AnalysisStatus.PROCESSING,
                updated_at=datetime.now(record.updated_at.tzinfo),
                record_version=record.record_version + 1,
            )
            self._records[analysis_id] = updated
            return updated

    async def save_result(
        self,
        analysis_id: str,
        result: AnalysisResult,
        artifacts: AnalysisArtifacts,
        completed_at: datetime,
    ) -> AnalysisRecord:
        async with self._lock:
            record = self._required(analysis_id)
            if record.status is not AnalysisStatus.PROCESSING:
                raise AnalysisConflictError("only processing analysis can publish a result")
            updated = replace(
                record,
                status=AnalysisStatus.READY,
                artifacts=artifacts,
                result=result,
                failure=None,
                completed_at=completed_at,
                updated_at=completed_at,
                record_version=record.record_version + 1,
            )
            self._records[analysis_id] = updated
            return updated

    async def mark_failed(
        self,
        analysis_id: str,
        failure: AnalysisFailure,
        failed_at: datetime,
    ) -> AnalysisRecord:
        async with self._lock:
            record = self._required(analysis_id)
            if record.status is not AnalysisStatus.PROCESSING:
                raise AnalysisConflictError("only processing analysis can fail")
            updated = replace(
                record,
                status=AnalysisStatus.FAILED,
                result=None,
                failure=failure,
                updated_at=failed_at,
                record_version=record.record_version + 1,
            )
            self._records[analysis_id] = updated
            return updated

    async def expire(self, analysis_id: str, expired_at: datetime) -> AnalysisRecord:
        async with self._lock:
            record = self._required(analysis_id)
            if record.status is AnalysisStatus.EXPIRED:
                return record
            if record.status is AnalysisStatus.PROCESSING:
                raise AnalysisConflictError("processing analysis cannot be expired")
            updated = replace(
                record,
                status=AnalysisStatus.EXPIRED,
                result=None,
                failure=None,
                completed_at=record.completed_at,
                expires_at=expired_at,
                updated_at=expired_at,
                record_version=record.record_version + 1,
            )
            self._records[analysis_id] = updated
            return updated

    async def add_artifacts(
        self,
        analysis_id: str,
        references: tuple[ArtifactReference, ...],
    ) -> AnalysisRecord:
        if not references:
            return await self.get(analysis_id)
        async with self._lock:
            record = self._required(analysis_id)
            if record.status is not AnalysisStatus.READY:
                raise AnalysisConflictError("derived artifacts require a ready analysis")
            unique = tuple(
                reference
                for reference in references
                if reference not in record.artifacts.all()
            )
            if not unique:
                return record
            updated = replace(
                record,
                artifacts=record.artifacts.with_references(unique),
                updated_at=datetime.now(record.updated_at.tzinfo),
                record_version=record.record_version + 1,
            )
            self._records[analysis_id] = updated
            return updated

    def _required(self, analysis_id: str) -> AnalysisRecord:
        try:
            return self._records[analysis_id]
        except KeyError as error:
            raise AnalysisNotFoundError(f"Analysis was not found: {analysis_id}.") from error

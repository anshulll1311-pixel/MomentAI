"""Single-flight orchestration for creating reusable immutable analyses."""

import asyncio
import hashlib
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.app.analysis.artifacts import ArtifactManager
from backend.app.analysis.errors import (
    AnalysisExecutionError,
    AnalysisExpiredError,
    AnalysisNotReadyError,
)
from backend.app.analysis.hooks import AnalysisLifecycleHook
from backend.app.analysis.models import (
    AnalysisArtifacts,
    AnalysisCoordinationResult,
    AnalysisFailure,
    AnalysisRecord,
    AnalysisStatus,
    ArtifactKind,
    ArtifactReference,
)
from backend.app.analysis.repository import AnalysisRepository
from backend.app.core.version import MIE_VERSION, PIPELINE_VERSION
from backend.app.services.moment_pipeline_service import AnalysisResult, MomentPipelineService

logger = logging.getLogger(__name__)
FINGERPRINT_CHUNK_SIZE = 1024 * 1024


class AnalysisCoordinator:
    """Create or reuse one versioned analysis for equivalent source media."""

    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        artifact_manager: ArtifactManager,
        pipeline: MomentPipelineService,
        hooks: Iterable[AnalysisLifecycleHook] = (),
        configuration_version: str = "default",
    ) -> None:
        if not configuration_version.strip():
            raise ValueError("analysis configuration version cannot be empty")
        self._repository = repository
        self._artifact_manager = artifact_manager
        self._pipeline = pipeline
        self._hooks = tuple(hooks)
        self._configuration_version = configuration_version
        self._inflight: dict[str, asyncio.Future[AnalysisRecord]] = {}
        self._inflight_lock = asyncio.Lock()

    @property
    def repository(self) -> AnalysisRepository:
        return self._repository

    async def create_or_reuse(
        self,
        *,
        source_path: Path,
        source_filename: str,
        profile_id: str = "default",
    ) -> AnalysisCoordinationResult:
        if not source_filename.strip() or not profile_id.strip():
            raise ValueError("source filename and profile ID are required")
        source_reference = self._artifact_manager.reference(
            ArtifactKind.SOURCE_MEDIA,
            source_path,
        )
        fingerprint = await asyncio.to_thread(_sha256_file, source_path)
        analysis_key = _analysis_key(
            fingerprint=fingerprint,
            profile_id=profile_id,
            configuration_version=self._configuration_version,
        )

        existing = await self._repository.find_by_key(analysis_key)
        if existing is not None and existing.status is AnalysisStatus.READY:
            await self._discard_duplicate_source(source_reference, existing)
            return AnalysisCoordinationResult(record=existing, reused=True)

        owner = False
        async with self._inflight_lock:
            future = self._inflight.get(analysis_key)
            if future is None:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._inflight[analysis_key] = future
                owner = True

        if not owner:
            record = await asyncio.shield(future)
            await self._discard_duplicate_source(source_reference, record)
            if record.status is AnalysisStatus.READY:
                return AnalysisCoordinationResult(record=record, reused=True)
            raise AnalysisExecutionError(
                record.analysis_id,
                record.failure.message if record.failure else "Analysis processing failed.",
            )

        analysis_id = f"ana_{uuid4().hex}"
        now = datetime.now(UTC)
        pending = AnalysisRecord(
            analysis_id=analysis_id,
            analysis_key=analysis_key,
            source_fingerprint=fingerprint,
            source_filename=Path(source_filename).name,
            profile_id=profile_id,
            status=AnalysisStatus.PENDING,
            artifacts=AnalysisArtifacts(source_media=source_reference),
            created_at=now,
            updated_at=now,
        )

        try:
            await self._repository.create_pending(pending)
            processing = await self._repository.mark_processing(analysis_id)
            await self._notify("analysis_started", processing)
            result = await self._pipeline.analyze(source_path, profile_id=profile_id)
            artifacts = self._artifacts_for(result, source_reference)
            completed = await self._repository.save_result(
                analysis_id,
                result,
                artifacts,
                datetime.now(UTC),
            )
            await self._notify("analysis_completed", completed)
            future.set_result(completed)
            return AnalysisCoordinationResult(record=completed, reused=False)
        except asyncio.CancelledError:
            failed = await self._fail(
                analysis_id,
                "CancelledError",
                "Analysis was cancelled.",
                True,
            )
            future.set_result(failed)
            raise
        except Exception as error:
            failed = await self._fail(
                analysis_id,
                type(error).__name__,
                str(error) or "Analysis processing failed.",
                isinstance(error, (TimeoutError, ConnectionError)),
            )
            future.set_result(failed)
            raise AnalysisExecutionError(analysis_id, failed.failure.message) from error
        finally:
            async with self._inflight_lock:
                self._inflight.pop(analysis_key, None)

    async def get_record(self, analysis_id: str) -> AnalysisRecord:
        return await self._repository.get(analysis_id)

    async def get_result(self, analysis_id: str) -> AnalysisResult:
        record = await self._repository.get(analysis_id)
        if record.status is AnalysisStatus.EXPIRED:
            raise AnalysisExpiredError(f"Analysis has expired: {analysis_id}.")
        if record.status is not AnalysisStatus.READY or record.result is None:
            raise AnalysisNotReadyError(
                f"Analysis is not ready: {analysis_id} ({record.status})."
            )
        return record.result

    async def expire(self, analysis_id: str) -> AnalysisRecord:
        record = await self._repository.get(analysis_id)
        await self._artifact_manager.delete_many(record.artifacts.all())
        expired = await self._repository.expire(analysis_id, datetime.now(UTC))
        await self._notify("analysis_expired", expired)
        return expired

    def artifact_reference(self, kind: ArtifactKind, path: Path) -> ArtifactReference:
        """Create a managed reference for a derived analysis artifact."""

        return self._artifact_manager.reference(kind, path)

    def resolve_artifact(self, reference: ArtifactReference) -> Path:
        """Resolve a managed reference for a local processing consumer."""

        return self._artifact_manager.resolve(reference)

    async def add_artifacts(
        self,
        analysis_id: str,
        references: tuple[ArtifactReference, ...],
    ) -> AnalysisRecord:
        """Attach derived references while leaving AnalysisResult immutable."""

        return await self._repository.add_artifacts(analysis_id, references)

    def _artifacts_for(
        self,
        result: AnalysisResult,
        source_reference: ArtifactReference,
    ) -> AnalysisArtifacts:
        thumbnails = tuple(
            self._artifact_manager.reference(ArtifactKind.THUMBNAIL, scene.thumbnail_path)
            for scene in result.scene_result.scenes
        )
        return AnalysisArtifacts(
            source_media=source_reference,
            thumbnails=thumbnails,
        )

    async def _fail(
        self,
        analysis_id: str,
        error_type: str,
        message: str,
        retryable: bool,
    ) -> AnalysisRecord:
        failure = AnalysisFailure(
            error_type=error_type,
            message=message,
            retryable=retryable,
        )
        failed = await self._repository.mark_failed(
            analysis_id,
            failure,
            datetime.now(UTC),
        )
        await self._notify("analysis_failed", failed)
        return failed

    async def _discard_duplicate_source(
        self,
        duplicate_reference: ArtifactReference,
        record: AnalysisRecord,
    ) -> None:
        if duplicate_reference.location != record.artifacts.source_media.location:
            await self._artifact_manager.delete(duplicate_reference)

    async def _notify(self, event: str, record: AnalysisRecord) -> None:
        for hook in self._hooks:
            try:
                callback = getattr(hook, event)
                await callback(record)
            except Exception:
                logger.exception(
                    "Analysis lifecycle hook failed event=%s analysis_id=%s",
                    event,
                    record.analysis_id,
                )


def _analysis_key(
    *,
    fingerprint: str,
    profile_id: str,
    configuration_version: str,
) -> str:
    material = "\n".join(
        (fingerprint, profile_id, PIPELINE_VERSION, MIE_VERSION, configuration_version)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(FINGERPRINT_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()

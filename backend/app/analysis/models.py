"""Immutable lifecycle models for reusable video analyses."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from backend.app.services.moment_pipeline_service import AnalysisResult


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class ArtifactKind(StrEnum):
    SOURCE_MEDIA = "source_media"
    THUMBNAIL = "thumbnail"
    SUBTITLE = "subtitle"
    EXPORTED_CLIP = "exported_clip"
    PREVIEW = "preview"


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Storage-provider-neutral reference; never contains artifact bytes."""

    kind: ArtifactKind
    location: str

    def __post_init__(self) -> None:
        if not self.location.strip():
            raise ValueError("artifact location cannot be empty")


@dataclass(frozen=True, slots=True)
class AnalysisArtifacts:
    source_media: ArtifactReference
    thumbnails: tuple[ArtifactReference, ...] = ()
    subtitle_files: tuple[ArtifactReference, ...] = ()
    exported_clips: tuple[ArtifactReference, ...] = ()
    preview_assets: tuple[ArtifactReference, ...] = ()

    def all(self) -> tuple[ArtifactReference, ...]:
        return (
            self.source_media,
            *self.thumbnails,
            *self.subtitle_files,
            *self.exported_clips,
            *self.preview_assets,
        )

    def with_references(
        self,
        references: tuple[ArtifactReference, ...],
    ) -> "AnalysisArtifacts":
        return AnalysisArtifacts(
            source_media=self.source_media,
            thumbnails=self.thumbnails
            + tuple(item for item in references if item.kind is ArtifactKind.THUMBNAIL),
            subtitle_files=self.subtitle_files
            + tuple(item for item in references if item.kind is ArtifactKind.SUBTITLE),
            exported_clips=self.exported_clips
            + tuple(item for item in references if item.kind is ArtifactKind.EXPORTED_CLIP),
            preview_assets=self.preview_assets
            + tuple(item for item in references if item.kind is ArtifactKind.PREVIEW),
        )


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    error_type: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    analysis_id: str
    analysis_key: str
    source_fingerprint: str
    source_filename: str
    profile_id: str
    status: AnalysisStatus
    artifacts: AnalysisArtifacts
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    result: AnalysisResult | None = None
    failure: AnalysisFailure | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        required = (
            self.analysis_id,
            self.analysis_key,
            self.source_fingerprint,
            self.source_filename,
            self.profile_id,
        )
        if not all(value.strip() for value in required):
            raise ValueError("analysis record identity fields cannot be empty")
        if self.record_version <= 0:
            raise ValueError("analysis record version must be positive")
        if self.status is AnalysisStatus.READY and self.result is None:
            raise ValueError("ready analysis record requires an immutable result")
        if self.result is not None and self.status is not AnalysisStatus.READY:
            raise ValueError("analysis result can only be published in the ready state")
        if self.failure is not None and self.status is not AnalysisStatus.FAILED:
            raise ValueError("analysis failure can only be stored in the failed state")


@dataclass(frozen=True, slots=True)
class AnalysisCoordinationResult:
    record: AnalysisRecord
    reused: bool

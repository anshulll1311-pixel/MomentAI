"""Export downloads and backward-compatible file-based export creation."""

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.app.analysis import AnalysisExecutionError, ArtifactKind
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import build_export_engine, get_analysis_coordinator
from backend.app.api.presenters import export_response
from backend.app.core.config import get_settings
from backend.app.exporting import ExportOptions, ExportPresetName
from backend.app.exporting.errors import (
    ClipValidationError,
    ExportArtifactNotFoundError,
    ExportPackageError,
    ExportPlanningError,
    ExportStorageError,
    ExportTimeoutError,
    ExportToolUnavailableError,
    FFmpegExecutionError,
    InsufficientExportStorageError,
)
from backend.app.exporting.storage import LocalArtifactStorage
from backend.app.schemas.exports import ExportResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(prefix="/exports", tags=["exports"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=ExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a video and synchronously export ranked moments",
    deprecated=True,
)
async def create_export(
    file: UploadFile = File(...),
    profile: str = Form(default="default", min_length=1, max_length=64),
    preset: ExportPresetName = Form(default=ExportPresetName.STANDARD),
    top_k: int = Form(default=5, ge=1, le=20),
    selected_ranks: str | None = Form(default=None, max_length=200),
    padding_before_seconds: float = Form(default=0.0, ge=0, le=30),
    padding_after_seconds: float = Form(default=0.0, ge=0, le=30),
) -> ExportResponse:
    """Compatibility adapter; new clients export by analysis_id."""

    settings = get_settings()
    try:
        options = ExportOptions(
            profile_id=profile,
            preset=preset,
            top_k=top_k,
            selected_ranks=_parse_selected_ranks(selected_ranks),
            padding_before_seconds=padding_before_seconds,
            padding_after_seconds=padding_after_seconds,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    try:
        stored = await store_upload(
            upload=file,
            destination=settings.upload_dir,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except EmptyFileError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except InvalidFileTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except FileTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    coordinator = get_analysis_coordinator()
    try:
        coordinated = await coordinator.create_or_reuse(
            source_path=stored.path,
            source_filename=stored.original_filename,
            profile_id=profile,
        )
    except AnalysisExecutionError as error:
        raise pipeline_http_exception(error) from error

    analysis = coordinated.record.result
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analysis result is not ready.",
        )
    try:
        result = await build_export_engine(settings).export(
            analysis=analysis,
            source_filename=coordinated.record.source_filename,
            options=options,
        )
        references = tuple(
            coordinator.artifact_reference(ArtifactKind.EXPORTED_CLIP, artifact.path)
            for artifact in result.artifacts
        )
        await coordinator.add_artifacts(coordinated.record.analysis_id, references)
    except (ExportPlanningError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ExportTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except ExportToolUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except InsufficientExportStorageError as error:
        raise HTTPException(status_code=507, detail=str(error)) from error
    except (
        FFmpegExecutionError,
        ClipValidationError,
        ExportPackageError,
        ExportStorageError,
    ) as error:
        logger.exception("Synchronous export failed analysis_id=%s", coordinated.record.analysis_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video export failed.",
        ) from error
    return export_response(result, api_prefix=settings.api_prefix)


@router.get("/{export_id}/clips/{clip_id}", summary="Download an exported clip")
async def download_clip(export_id: str, clip_id: str) -> FileResponse:
    path = _resolve_artifact("clip", export_id, clip_id)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/{export_id}/manifest", summary="Download an export manifest")
async def download_manifest(export_id: str) -> FileResponse:
    path = _resolve_artifact("manifest", export_id)
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"momentai-export-{export_id}-manifest.json",
    )


@router.get("/{export_id}/package", summary="Download an export package")
async def download_package(export_id: str) -> FileResponse:
    path = _resolve_artifact("package", export_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


def _resolve_artifact(kind: str, export_id: str, clip_id: str | None = None) -> Path:
    settings = get_settings()
    storage = LocalArtifactStorage(settings.export_dir, settings.export_temp_dir)
    try:
        if kind == "clip" and clip_id is not None:
            return storage.resolve_clip(export_id, clip_id)
        if kind == "manifest":
            return storage.resolve_manifest(export_id)
        return storage.resolve_package(export_id)
    except ExportArtifactNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _parse_selected_ranks(value: str | None) -> tuple[int, ...]:
    if value is None or not value.strip():
        return ()
    try:
        return tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise ValueError("selected_ranks must be a comma-separated list of integers") from error

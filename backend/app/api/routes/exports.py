import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.app.core.config import Settings, get_settings
from backend.app.exporting import ExportEngine, ExportOptions, ExportPresetName
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
from backend.app.exporting.ffmpeg import (
    FFmpegClipExtractor,
    FFmpegCommandBuilder,
    FFmpegProcessRunner,
    FFprobeOutputValidator,
)
from backend.app.exporting.packaging import ZipPackageBuilder
from backend.app.exporting.planner import ExportPlanner
from backend.app.exporting.storage import LocalArtifactStorage
from backend.app.intelligence import create_default_engine
from backend.app.intelligence.registry import AnalyzerConfigurationError
from backend.app.schemas.exports import (
    ExportClipResponse,
    ExportDiagnosticResponse,
    ExportResponse,
)
from backend.app.services.moment_pipeline_service import MomentPipelineService
from backend.app.services.scene_service import (
    SceneDetectionError,
    SceneService,
    SceneServiceError,
    SceneThumbnailError,
    SceneTimeoutError,
    SceneToolUnavailableError,
)
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    StoredUpload,
    store_upload,
)
from backend.app.services.transcript_service import TranscriptService
from backend.app.services.video_service import (
    InvalidVideoError,
    VideoProbeTimeoutError,
    VideoProcessingError,
    VideoService,
    VideoToolUnavailableError,
)

router = APIRouter(prefix="/exports", tags=["exports"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=ExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a video and synchronously export ranked moments",
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
    settings = get_settings()
    try:
        ranks = _parse_selected_ranks(selected_ranks)
        options = ExportOptions(
            profile_id=profile,
            preset=preset,
            top_k=top_k,
            selected_ranks=ranks,
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

    pipeline = _build_moment_pipeline(settings)
    try:
        analysis = await pipeline.analyze(stored.path, profile_id=profile)
        export_result = await _build_export_engine(settings).export(
            analysis=analysis,
            source_filename=stored.original_filename,
            options=options,
        )
    except KeyError as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except (InvalidVideoError, SceneDetectionError, SceneThumbnailError) as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (ExportPlanningError, ValueError) as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProbeTimeoutError, SceneTimeoutError, ExportTimeoutError) as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (
        VideoToolUnavailableError,
        SceneToolUnavailableError,
        ExportToolUnavailableError,
    ) as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except InsufficientExportStorageError as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(status_code=507, detail=str(error)) from error
    except (
        VideoProcessingError,
        SceneServiceError,
        AnalyzerConfigurationError,
        FFmpegExecutionError,
        ClipValidationError,
        ExportPackageError,
        ExportStorageError,
    ) as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        logger.exception("Synchronous export failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video export failed.",
        ) from error
    except Exception as error:
        _discard_source_artifacts(stored, settings.thumbnail_dir)
        logger.exception("Unexpected synchronous export failure for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video export failed.",
        ) from error

    _discard_source_artifacts(stored, settings.thumbnail_dir)
    return ExportResponse(
        success=True,
        export_id=export_result.export_id,
        profile=export_result.profile_id,
        preset=export_result.preset,
        clip_count=len(export_result.artifacts),
        clips=[
            ExportClipResponse(
                clip_id=artifact.spec.clip_id,
                rank=artifact.spec.rank,
                start=round(artifact.spec.start_seconds, 3),
                end=round(artifact.spec.end_seconds, 3),
                duration=round(artifact.metadata.duration_seconds, 3),
                score=round(artifact.spec.score, 6),
                size_bytes=artifact.metadata.size_bytes,
                sha256=artifact.sha256,
                download_url=(
                    f"{settings.api_prefix}/exports/{export_result.export_id}/"
                    f"clips/{artifact.spec.clip_id}"
                ),
            )
            for artifact in export_result.artifacts
        ],
        manifest_url=f"{settings.api_prefix}/exports/{export_result.export_id}/manifest",
        package_url=f"{settings.api_prefix}/exports/{export_result.export_id}/package",
        package_sha256=export_result.package_sha256,
        diagnostics=[
            ExportDiagnosticResponse(
                stage=item.stage,
                status=item.status,
                message=item.message,
            )
            for item in export_result.manifest.diagnostics
        ],
    )


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


def _build_moment_pipeline(settings: Settings) -> MomentPipelineService:
    video_service = VideoService(
        ffprobe_binary=settings.ffprobe_binary,
        timeout_seconds=settings.ffprobe_timeout_seconds,
    )
    scene_service = SceneService(
        video_service=video_service,
        thumbnail_directory=settings.thumbnail_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        threshold=settings.scene_threshold,
        minimum_scene_duration_seconds=settings.minimum_scene_duration_seconds,
        detection_timeout_seconds=settings.scene_detection_timeout_seconds,
        thumbnail_timeout_seconds=settings.ffmpeg_timeout_seconds,
    )
    transcript_service = TranscriptService(
        video_service=video_service,
        scene_service=scene_service,
        temporary_directory=settings.transcript_temp_dir,
        model_directory=settings.whisper_model_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        beam_size=settings.whisper_beam_size,
        audio_timeout_seconds=settings.audio_extraction_timeout_seconds,
        transcription_timeout_seconds=settings.transcription_timeout_seconds,
    )
    return MomentPipelineService(
        video_service=video_service,
        scene_service=scene_service,
        transcript_service=transcript_service,
        engine=create_default_engine(),
    )


def _build_export_engine(settings: Settings) -> ExportEngine:
    return ExportEngine(
        planner=ExportPlanner(),
        clip_extractor=FFmpegClipExtractor(
            command_builder=FFmpegCommandBuilder(settings.ffmpeg_binary),
            process_runner=FFmpegProcessRunner(settings.export_ffmpeg_timeout_seconds),
            output_validator=FFprobeOutputValidator(
                settings.ffprobe_binary,
                settings.export_ffprobe_timeout_seconds,
            ),
        ),
        package_builder=ZipPackageBuilder(),
        artifact_storage=LocalArtifactStorage(
            settings.export_dir,
            settings.export_temp_dir,
        ),
    )


def _parse_selected_ranks(value: str | None) -> tuple[int, ...]:
    if value is None or not value.strip():
        return ()
    try:
        return tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise ValueError("selected_ranks must be a comma-separated list of integers") from error


def _discard_source_artifacts(stored: StoredUpload, thumbnail_directory: Path) -> None:
    try:
        stored.path.unlink(missing_ok=True)
        shutil.rmtree(thumbnail_directory / "scenes" / stored.path.stem, ignore_errors=True)
    except OSError:
        logger.exception("Failed to remove completed export source artifacts for %s", stored.filename)

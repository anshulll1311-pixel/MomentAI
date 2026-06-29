import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.intelligence import create_default_engine
from backend.app.intelligence.registry import AnalyzerConfigurationError
from backend.app.schemas.moments import (
    AnalyzerExecutionResponse,
    MomentInsightResponse,
    MomentsResponse,
    PipelineDiagnosticResponse,
    RankedMomentResponse,
    SignalContributionResponse,
)
from backend.app.services.moment_pipeline_service import MomentPipelineResult, MomentPipelineService
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

router = APIRouter(tags=["moments"])
logger = logging.getLogger(__name__)


@router.post(
    "/moments",
    response_model=MomentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Rank deterministic moments from a video",
)
async def rank_video_moments(
    file: UploadFile = File(...),
    profile: str = Query(default="default", min_length=1, max_length=64),
) -> MomentsResponse:
    settings = get_settings()
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
    pipeline = MomentPipelineService(
        video_service=video_service,
        scene_service=scene_service,
        transcript_service=transcript_service,
        engine=create_default_engine(),
    )

    try:
        result = await pipeline.analyze(stored.path, profile_id=profile)
    except KeyError as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except InvalidVideoError as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProbeTimeoutError, SceneTimeoutError) as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (VideoToolUnavailableError, SceneToolUnavailableError) as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (SceneDetectionError, SceneThumbnailError) as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProcessingError, SceneServiceError, AnalyzerConfigurationError) as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        logger.exception("Moment pipeline failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Moment Intelligence processing failed.",
        ) from error
    except Exception as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        logger.exception("Unexpected Moment pipeline failure for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Moment Intelligence processing failed.",
        ) from error

    try:
        return _build_response(stored, result, settings.thumbnail_dir)
    except Exception as error:
        _discard_pipeline_artifacts(stored, settings.thumbnail_dir)
        logger.exception("Moment response construction failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Moment Intelligence response could not be created.",
        ) from error


def _build_response(
    stored: StoredUpload,
    result: MomentPipelineResult,
    thumbnail_directory: Path,
) -> MomentsResponse:
    thumbnails_by_scene = {
        scene.id: f"/thumbnails/{scene.thumbnail_path.relative_to(thumbnail_directory).as_posix()}"
        for scene in result.scene_result.scenes
    }
    return MomentsResponse(
        success=True,
        profile=result.engine_result.profile_id,
        filename=stored.original_filename,
        duration=round(result.video_metadata.duration_seconds, 3),
        scene_count=len(result.scene_result.scenes),
        transcript_language=(
            result.transcript_result.language if result.transcript_result is not None else None
        ),
        transcript_segment_count=(
            len(result.transcript_result.segments) if result.transcript_result is not None else 0
        ),
        moments=[
            RankedMomentResponse(
                rank=rank,
                candidate_id=moment.candidate.candidate_id,
                start=round(moment.candidate.start_seconds, 3),
                end=round(moment.candidate.end_seconds, 3),
                duration=round(moment.candidate.duration_seconds, 3),
                scene_ids=list(moment.candidate.scene_ids),
                score=round(moment.score, 6),
                confidence=round(moment.confidence, 6),
                thumbnails=[
                    thumbnails_by_scene[scene_id]
                    for scene_id in moment.candidate.scene_ids
                    if scene_id in thumbnails_by_scene
                ],
                contributions=[
                    SignalContributionResponse(
                        analyzer_id=item.analyzer_id,
                        signal_name=item.signal_name,
                        raw_score=round(item.raw_score, 6),
                        confidence=round(item.confidence, 6),
                        weight=item.weight,
                        weighted_value=round(item.weighted_value, 6),
                    )
                    for item in moment.contributions
                ],
                insights=[
                    MomentInsightResponse(
                        insight_type=item.insight_type,
                        summary=item.summary,
                        evidence=dict(item.evidence),
                    )
                    for item in moment.insights
                ],
            )
            for rank, moment in enumerate(result.engine_result.moments, start=1)
        ],
        analyzers=[
            AnalyzerExecutionResponse(
                analyzer_id=item.analyzer_id,
                version=item.version,
                status=str(item.status),
                duration_ms=round(item.duration_ms, 3),
                cache_key=item.cache_key,
                error=item.error,
            )
            for item in result.engine_result.executions
        ],
        diagnostics=[
            PipelineDiagnosticResponse(
                stage=item.stage,
                status=item.status,
                message=item.message,
            )
            for item in result.diagnostics
        ],
    )


def _discard_pipeline_artifacts(stored: StoredUpload, thumbnail_directory: Path) -> None:
    try:
        stored.path.unlink(missing_ok=True)
        scene_directory = thumbnail_directory / "scenes" / stored.path.stem
        shutil.rmtree(scene_directory, ignore_errors=True)
        logger.info("Removed failed Moment Intelligence artifacts for %s", stored.filename)
    except OSError:
        logger.exception("Failed to remove Moment Intelligence artifacts for %s", stored.filename)

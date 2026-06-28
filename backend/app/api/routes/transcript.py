import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.schemas.transcript import TranscriptResponse, TranscriptSegmentResponse
from backend.app.services.scene_service import (
    SceneDetectionError,
    SceneService,
    SceneServiceError,
    SceneTimeoutError,
    SceneToolUnavailableError,
)
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)
from backend.app.services.transcript_service import (
    AudioExtractionError,
    AudioToolUnavailableError,
    EmptyTranscriptError,
    MissingAudioError,
    TranscriptService,
    TranscriptServiceError,
    TranscriptionError,
    TranscriptionTimeoutError,
    TranscriptionUnavailableError,
)
from backend.app.services.video_service import (
    InvalidVideoError,
    VideoProbeTimeoutError,
    VideoProcessingError,
    VideoService,
    VideoToolUnavailableError,
)

router = APIRouter(tags=["transcript"])
logger = logging.getLogger(__name__)


@router.post(
    "/transcript",
    response_model=TranscriptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a timestamped video transcript",
)
async def create_video_transcript(file: UploadFile = File(...)) -> TranscriptResponse:
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

    try:
        result = await transcript_service.transcribe(stored.path)
    except (MissingAudioError, EmptyTranscriptError, AudioExtractionError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except InvalidVideoError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProbeTimeoutError, SceneTimeoutError, TranscriptionTimeoutError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (
        VideoToolUnavailableError,
        SceneToolUnavailableError,
        AudioToolUnavailableError,
        TranscriptionUnavailableError,
    ) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except SceneDetectionError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProcessingError, SceneServiceError, TranscriptionError) as error:
        _discard_upload(stored.path)
        logger.exception("Transcript processing failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcript processing failed.",
        ) from error
    except TranscriptServiceError as error:
        _discard_upload(stored.path)
        logger.exception("Unexpected transcript error for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcript processing failed.",
        ) from error

    return TranscriptResponse(
        success=True,
        language=result.language,
        duration=round(result.duration_seconds, 3),
        segments=[
            TranscriptSegmentResponse(
                start=round(segment.start_seconds, 3),
                end=round(segment.end_seconds, 3),
                text=segment.text,
                scene_id=segment.scene_id,
            )
            for segment in result.segments
        ],
    )


def _discard_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        logger.info("Removed failed transcript upload %s", path.name)
    except OSError:
        logger.exception("Failed to remove transcript upload %s", path.name)

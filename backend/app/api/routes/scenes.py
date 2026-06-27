import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.schemas.scenes import SceneResponse, ScenesResponse
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
    store_upload,
)
from backend.app.services.video_service import (
    InvalidVideoError,
    VideoProbeTimeoutError,
    VideoProcessingError,
    VideoService,
    VideoToolUnavailableError,
)

router = APIRouter(tags=["scenes"])
logger = logging.getLogger(__name__)


@router.post(
    "/scenes",
    response_model=ScenesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Detect logical scenes in a video",
)
async def detect_video_scenes(file: UploadFile = File(...)) -> ScenesResponse:
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

    scene_service = SceneService(
        video_service=VideoService(
            ffprobe_binary=settings.ffprobe_binary,
            timeout_seconds=settings.ffprobe_timeout_seconds,
        ),
        thumbnail_directory=settings.thumbnail_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        threshold=settings.scene_threshold,
        minimum_scene_duration_seconds=settings.minimum_scene_duration_seconds,
        detection_timeout_seconds=settings.scene_detection_timeout_seconds,
        thumbnail_timeout_seconds=settings.ffmpeg_timeout_seconds,
    )

    try:
        result = await scene_service.detect_scenes(stored.path)
    except InvalidVideoError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProbeTimeoutError, SceneTimeoutError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (VideoToolUnavailableError, SceneToolUnavailableError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (SceneDetectionError, SceneThumbnailError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProcessingError, SceneServiceError) as error:
        _discard_upload(stored.path)
        logger.exception("Scene processing failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scene processing failed.",
        ) from error

    scenes = [
        SceneResponse(
            id=scene.id,
            start=_format_timestamp(scene.start_seconds),
            end=_format_timestamp(scene.end_seconds),
            duration=round(scene.duration_seconds, 3),
            thumbnail=f"/thumbnails/{scene.thumbnail_path.relative_to(settings.thumbnail_dir).as_posix()}",
        )
        for scene in result.scenes
    ]
    return ScenesResponse(success=True, scene_count=len(scenes), scenes=scenes)


def _format_timestamp(seconds: float) -> str:
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    base = f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
    return f"{base}.{milliseconds:03d}" if milliseconds else base


def _discard_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        logger.info("Removed failed scene upload %s", path.name)
    except OSError:
        logger.exception("Failed to remove scene upload %s", path.name)

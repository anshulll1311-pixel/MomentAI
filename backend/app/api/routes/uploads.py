import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.schemas.upload import UploadResponse, VideoMetadataResponse
from backend.app.services.storage import (
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

router = APIRouter(prefix="/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a source video",
)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    settings = get_settings()

    try:
        stored = await store_upload(
            upload=file,
            destination=settings.upload_dir,
            max_size_bytes=settings.max_upload_size_bytes,
        )
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
    try:
        metadata = await video_service.extract_metadata(stored.path)
    except InvalidVideoError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except VideoProbeTimeoutError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except VideoToolUnavailableError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except VideoProcessingError as error:
        _discard_upload(stored.path)
        logger.exception("Video metadata processing failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video metadata processing failed.",
        ) from error

    return UploadResponse(
        status="success",
        message="Video uploaded successfully.",
        original_filename=stored.original_filename,
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
        metadata=VideoMetadataResponse(
            duration_seconds=metadata.duration_seconds,
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
            file_size_bytes=metadata.file_size_bytes,
        ),
    )


def _discard_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        logger.info("Removed rejected upload %s", path.name)
    except OSError:
        logger.exception("Failed to remove rejected upload %s", path.name)

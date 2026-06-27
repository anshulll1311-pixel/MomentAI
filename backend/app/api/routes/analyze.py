import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.schemas.analysis import AnalysisResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)
from backend.app.services.video_analyzer import (
    AnalysisTimeoutError,
    FFmpegUnavailableError,
    ThumbnailGenerationError,
    VideoAnalyzer,
)
from backend.app.services.video_service import (
    InvalidVideoError,
    VideoProbeTimeoutError,
    VideoProcessingError,
    VideoService,
    VideoToolUnavailableError,
)

router = APIRouter(tags=["analysis"])
logger = logging.getLogger(__name__)


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a video and generate its thumbnail",
)
async def analyze_video(file: UploadFile = File(...)) -> AnalysisResponse:
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

    analyzer = VideoAnalyzer(
        video_service=VideoService(
            ffprobe_binary=settings.ffprobe_binary,
            timeout_seconds=settings.ffprobe_timeout_seconds,
        ),
        thumbnail_directory=settings.thumbnail_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        timeout_seconds=settings.ffmpeg_timeout_seconds,
    )

    try:
        analysis = await analyzer.analyze(stored.path)
    except InvalidVideoError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (VideoProbeTimeoutError, AnalysisTimeoutError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (VideoToolUnavailableError, FFmpegUnavailableError) as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ThumbnailGenerationError as error:
        _discard_upload(stored.path)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except VideoProcessingError as error:
        _discard_upload(stored.path)
        logger.exception("Video analysis failed for %s", stored.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video analysis failed.",
        ) from error

    metadata = analysis.metadata
    return AnalysisResponse(
        success=True,
        filename=stored.original_filename,
        duration=metadata.duration_seconds,
        width=metadata.width,
        height=metadata.height,
        fps=metadata.fps,
        video_codec=metadata.video_codec,
        audio_codec=metadata.audio_codec,
        bitrate=metadata.bitrate,
        rotation=metadata.rotation,
        thumbnail=f"/thumbnails/{analysis.thumbnail_path.name}",
        filesize=metadata.file_size_bytes,
    )


def _discard_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        logger.info("Removed failed analysis upload %s", path.name)
    except OSError:
        logger.exception("Failed to remove analysis upload %s", path.name)

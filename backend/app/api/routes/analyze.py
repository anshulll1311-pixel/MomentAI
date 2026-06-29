"""Backward-compatible metadata/thumbnail projection from AnalysisResult."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.analysis import AnalysisExecutionError, ArtifactKind
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import get_analysis_coordinator
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
from backend.app.services.video_service import VideoService

router = APIRouter(tags=["analysis"])


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a video and generate its thumbnail",
    deprecated=True,
)
async def analyze_video(file: UploadFile = File(...)) -> AnalysisResponse:
    """Compatibility adapter; canonical clients retrieve analysis by ID."""

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

    coordinator = get_analysis_coordinator()
    try:
        coordinated = await coordinator.create_or_reuse(
            source_path=stored.path,
            source_filename=stored.original_filename,
        )
    except AnalysisExecutionError as error:
        raise pipeline_http_exception(error) from error
    result = coordinated.record.result
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Analysis is not ready.")

    metadata = result.video_metadata
    preview_reference = next(
        (
            reference
            for reference in coordinated.record.artifacts.preview_assets
            if coordinator.resolve_artifact(reference).is_file()
        ),
        None,
    )
    if preview_reference is None:
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
            thumbnail = await analyzer.generate_thumbnail(
                result.source_path,
                metadata.duration_seconds / 2,
            )
        except AnalysisTimeoutError as error:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=str(error),
            ) from error
        except FFmpegUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        except ThumbnailGenerationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        preview_reference = coordinator.artifact_reference(ArtifactKind.PREVIEW, thumbnail)
        await coordinator.add_artifacts(
            coordinated.record.analysis_id,
            (preview_reference,),
        )
    thumbnail = coordinator.resolve_artifact(preview_reference)
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
        thumbnail=f"/thumbnails/{thumbnail.relative_to(settings.thumbnail_dir).as_posix()}",
        filesize=metadata.file_size_bytes,
    )

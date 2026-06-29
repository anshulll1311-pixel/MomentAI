"""Backward-compatible upload projection over the reusable analysis lifecycle."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.analysis import AnalysisExecutionError
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import get_analysis_coordinator
from backend.app.core.config import get_settings
from backend.app.schemas.upload import UploadResponse, VideoMetadataResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a source video",
    deprecated=True,
)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    """Compatibility adapter; canonical clients use POST /analyses."""

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

    try:
        coordinated = await get_analysis_coordinator().create_or_reuse(
            source_path=stored.path,
            source_filename=stored.original_filename,
        )
    except AnalysisExecutionError as error:
        raise pipeline_http_exception(error) from error
    result = coordinated.record.result
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Analysis is not ready.")
    metadata = result.video_metadata
    return UploadResponse(
        status="success",
        message="Video uploaded successfully.",
        original_filename=stored.original_filename,
        filename=result.source_path.name,
        size_bytes=metadata.file_size_bytes,
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

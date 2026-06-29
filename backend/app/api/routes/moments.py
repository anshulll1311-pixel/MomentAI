"""Backward-compatible file endpoint for deterministic ranked moments."""

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.app.analysis import AnalysisExecutionError
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import get_analysis_coordinator
from backend.app.api.presenters import moments_response
from backend.app.core.config import get_settings
from backend.app.schemas.moments import MomentsResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(tags=["moments"])


@router.post(
    "/moments",
    response_model=MomentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Rank deterministic moments from a video",
    deprecated=True,
)
async def rank_video_moments(
    file: UploadFile = File(...),
    profile: str = Query(default="default", min_length=1, max_length=64),
) -> MomentsResponse:
    """Compatibility adapter; new clients should create an analysis once."""

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
            profile_id=profile,
        )
    except AnalysisExecutionError as error:
        raise pipeline_http_exception(error) from error

    result = coordinated.record.result
    if result is None:  # Defensive: coordinator only returns ready records.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analysis result is not ready.",
        )
    return moments_response(
        result,
        source_filename=coordinated.record.source_filename,
        thumbnail_directory=settings.thumbnail_dir,
    )

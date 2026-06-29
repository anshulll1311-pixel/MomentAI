"""Backward-compatible transcript projection from a reusable analysis."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.analysis import AnalysisExecutionError
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import get_analysis_coordinator
from backend.app.core.config import get_settings
from backend.app.schemas.transcript import TranscriptResponse, TranscriptSegmentResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(tags=["transcript"])


@router.post(
    "/transcript",
    response_model=TranscriptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a timestamped video transcript",
    deprecated=True,
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
    transcript = result.transcript_result
    if transcript is None:
        diagnostic = next(
            (item.message for item in result.diagnostics if item.stage == "transcript"),
            "A transcript could not be generated for this video.",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=diagnostic,
        )

    return TranscriptResponse(
        success=True,
        language=transcript.language,
        duration=round(transcript.duration_seconds, 3),
        segments=[
            TranscriptSegmentResponse(
                start=round(segment.start_seconds, 3),
                end=round(segment.end_seconds, 3),
                text=segment.text,
                scene_id=segment.scene_id,
            )
            for segment in transcript.segments
        ],
    )

"""Backward-compatible scene projection from a reusable analysis."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.analysis import AnalysisExecutionError
from backend.app.api.analysis_errors import pipeline_http_exception
from backend.app.api.dependencies import get_analysis_coordinator
from backend.app.core.config import get_settings
from backend.app.schemas.scenes import SceneResponse, ScenesResponse
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(tags=["scenes"])


@router.post(
    "/scenes",
    response_model=ScenesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Detect logical scenes in a video",
    deprecated=True,
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

    scenes = [
        SceneResponse(
            id=scene.id,
            start=_format_timestamp(scene.start_seconds),
            end=_format_timestamp(scene.end_seconds),
            duration=round(scene.duration_seconds, 3),
            thumbnail=(
                f"/thumbnails/{scene.thumbnail_path.relative_to(settings.thumbnail_dir).as_posix()}"
            ),
        )
        for scene in result.scene_result.scenes
    ]
    return ScenesResponse(success=True, scene_count=len(scenes), scenes=scenes)


def _format_timestamp(seconds: float) -> str:
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    base = f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
    return f"{base}.{milliseconds:03d}" if milliseconds else base

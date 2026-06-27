from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.schemas.upload import UploadResponse
from backend.app.services.storage import (
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

    return UploadResponse(
        status="success",
        message="Video uploaded successfully.",
        original_filename=stored.original_filename,
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )

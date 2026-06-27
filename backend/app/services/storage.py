import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import UploadFile

ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi"})
CHUNK_SIZE_BYTES = 1024 * 1024


class InvalidFileTypeError(ValueError):
    """Raised when an upload does not have an allowed video extension."""


class FileTooLargeError(ValueError):
    """Raised when an upload exceeds the configured size limit."""


@dataclass(frozen=True, slots=True)
class StoredUpload:
    original_filename: str
    filename: str
    size_bytes: int
    content_type: str | None


def _build_storage_name(original_filename: str) -> tuple[str, str]:
    original_name = Path(original_filename).name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
        raise InvalidFileTypeError(f"Unsupported file type. Allowed extensions: {allowed}.")

    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(original_name).stem).strip("-_")
    safe_stem = safe_stem[:80] or "video"
    return original_name, f"{safe_stem}-{uuid4().hex}{extension}"


async def store_upload(
    upload: UploadFile,
    destination: Path,
    max_size_bytes: int,
) -> StoredUpload:
    """Validate and stream an uploaded video to local storage."""
    if not upload.filename:
        raise InvalidFileTypeError("A filename is required.")

    original_name, storage_name = _build_storage_name(upload.filename)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / storage_name
    total_bytes = 0

    try:
        async with aiofiles.open(output_path, "xb") as output:
            while chunk := await upload.read(CHUNK_SIZE_BYTES):
                total_bytes += len(chunk)
                if total_bytes > max_size_bytes:
                    raise FileTooLargeError(
                        f"File exceeds the {max_size_bytes // (1024 * 1024)} MB upload limit."
                    )
                await output.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return StoredUpload(
        original_filename=original_name,
        filename=storage_name,
        size_bytes=total_bytes,
        content_type=upload.content_type,
    )

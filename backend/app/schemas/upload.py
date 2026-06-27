from typing import Literal

from pydantic import BaseModel


class UploadResponse(BaseModel):
    status: Literal["success"]
    message: str
    original_filename: str
    filename: str
    size_bytes: int
    content_type: str | None

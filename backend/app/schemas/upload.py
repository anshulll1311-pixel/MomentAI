from typing import Literal

from pydantic import BaseModel


class VideoMetadataResponse(BaseModel):
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    file_size_bytes: int


class UploadResponse(BaseModel):
    status: Literal["success"]
    message: str
    original_filename: str
    filename: str
    size_bytes: int
    content_type: str | None
    metadata: VideoMetadataResponse

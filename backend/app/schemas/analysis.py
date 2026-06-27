from typing import Literal

from pydantic import BaseModel


class AnalysisResponse(BaseModel):
    success: Literal[True]
    filename: str
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    bitrate: int
    rotation: int | None
    thumbnail: str
    filesize: int

from typing import Literal

from pydantic import BaseModel


class TranscriptSegmentResponse(BaseModel):
    start: float
    end: float
    text: str
    scene_id: int


class TranscriptResponse(BaseModel):
    success: Literal[True]
    language: str
    duration: float
    segments: list[TranscriptSegmentResponse]

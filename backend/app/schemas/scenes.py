from typing import Literal

from pydantic import BaseModel


class SceneResponse(BaseModel):
    id: int
    start: str
    end: str
    duration: float
    thumbnail: str


class ScenesResponse(BaseModel):
    success: Literal[True]
    scene_count: int
    scenes: list[SceneResponse]

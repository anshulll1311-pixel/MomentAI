from typing import Literal

from pydantic import BaseModel

from backend.app.exporting.models import ExportPresetName


class ExportDiagnosticResponse(BaseModel):
    stage: str
    status: str
    message: str


class ExportClipResponse(BaseModel):
    clip_id: str
    rank: int
    start: float
    end: float
    duration: float
    score: float
    size_bytes: int
    sha256: str
    download_url: str


class ExportResponse(BaseModel):
    success: Literal[True]
    export_id: str
    profile: str
    preset: ExportPresetName
    clip_count: int
    clips: list[ExportClipResponse]
    manifest_url: str
    package_url: str
    package_sha256: str
    diagnostics: list[ExportDiagnosticResponse]

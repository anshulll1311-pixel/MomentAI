from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.analysis import AnalysisStatus
from backend.app.exporting import ExportPresetName


class AnalysisSummaryResponse(BaseModel):
    duration: float
    width: int
    height: int
    scene_count: int
    transcript_language: str | None
    transcript_segment_count: int
    moment_count: int


class AnalysisRecordResponse(BaseModel):
    success: Literal[True]
    analysis_id: str
    status: AnalysisStatus
    reused: bool | None
    filename: str
    profile: str
    source_fingerprint: str
    created_at: datetime
    completed_at: datetime | None
    summary: AnalysisSummaryResponse | None
    failure: str | None
    moments_url: str
    semantic_url: str
    export_url: str


class SemanticGenerationRequest(BaseModel):
    provider_id: str = Field(default="auto", min_length=1, max_length=64)
    locale: str = Field(default="en", min_length=1, max_length=32)
    tone: str = Field(default="neutral", min_length=1, max_length=64)
    selected_ranks: list[int] = Field(default_factory=list, max_length=100)


class SemanticMomentResponse(BaseModel):
    candidate_id: str
    rank: int
    status: str
    content_origin: str
    title: str | None
    description: str | None
    hashtags: list[str]
    explanation: str | None


class SemanticDiagnosticResponse(BaseModel):
    stage: str
    status: str
    message: str
    candidate_id: str | None
    provider_id: str | None
    retryable: bool


class AnalysisSemanticResponse(BaseModel):
    success: Literal[True]
    analysis_id: str
    status: str
    provider_id: str | None
    model_id: str | None
    batch_count: int
    cache_hits: int
    moments: list[SemanticMomentResponse]
    diagnostics: list[SemanticDiagnosticResponse]


class AnalysisExportRequest(BaseModel):
    preset: ExportPresetName = ExportPresetName.STANDARD
    top_k: int = Field(default=5, ge=1, le=20)
    selected_ranks: list[int] = Field(default_factory=list, max_length=20)
    padding_before_seconds: float = Field(default=0.0, ge=0, le=30)
    padding_after_seconds: float = Field(default=0.0, ge=0, le=30)

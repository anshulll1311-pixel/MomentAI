from typing import Any, Literal

from pydantic import BaseModel


class SignalContributionResponse(BaseModel):
    analyzer_id: str
    signal_name: str
    raw_score: float
    confidence: float
    weight: float
    weighted_value: float


class MomentInsightResponse(BaseModel):
    insight_type: str
    summary: str
    evidence: dict[str, Any]


class RankedMomentResponse(BaseModel):
    rank: int
    candidate_id: str
    start: float
    end: float
    duration: float
    scene_ids: list[int]
    score: float
    confidence: float
    thumbnails: list[str]
    contributions: list[SignalContributionResponse]
    insights: list[MomentInsightResponse]


class AnalyzerExecutionResponse(BaseModel):
    analyzer_id: str
    version: str
    status: str
    duration_ms: float
    cache_key: str | None
    error: str | None


class PipelineDiagnosticResponse(BaseModel):
    stage: str
    status: str
    message: str


class MomentsResponse(BaseModel):
    success: Literal[True]
    profile: str
    filename: str
    duration: float
    scene_count: int
    transcript_language: str | None
    transcript_segment_count: int
    moments: list[RankedMomentResponse]
    analyzers: list[AnalyzerExecutionResponse]
    diagnostics: list[PipelineDiagnosticResponse]

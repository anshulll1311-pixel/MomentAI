from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from backend.app.services.scene_service import Scene
from backend.app.services.transcript_service import TranscriptSegment
from backend.app.services.video_service import VideoMetadata


class EstimatedCost(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnalyzerExecutionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AnalyzerMetadata:
    analyzer_id: str
    version: str
    priority: int
    dependencies: tuple[str, ...]
    estimated_cost: EstimatedCost
    cacheable: bool

    def __post_init__(self) -> None:
        if not self.analyzer_id.strip():
            raise ValueError("analyzer_id cannot be empty")
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if self.priority < 0:
            raise ValueError("priority cannot be negative")
        if self.analyzer_id in self.dependencies:
            raise ValueError("analyzer cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("analyzer dependencies must be unique")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    source_fingerprint: str
    video_path: Path
    video_metadata: VideoMetadata
    scenes: tuple[Scene, ...]
    transcript_segments: tuple[TranscriptSegment, ...] = ()
    resources: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_fingerprint.strip():
            raise ValueError("source_fingerprint cannot be empty")
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))


@dataclass(frozen=True, slots=True)
class MomentCandidate:
    candidate_id: str
    start_seconds: float
    end_seconds: float
    scene_ids: tuple[int, ...]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id cannot be empty")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("candidate timeline is invalid")
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class Signal:
    analyzer_id: str
    candidate_id: str
    signal_name: str
    score: float
    confidence: float
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.analyzer_id.strip() or not self.candidate_id.strip():
            raise ValueError("signal analyzer_id and candidate_id are required")
        if not self.signal_name.strip():
            raise ValueError("signal_name cannot be empty")
        if not 0 <= self.score <= 1:
            raise ValueError("signal score must be between 0 and 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("signal confidence must be between 0 and 1")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class SignalBatch:
    analyzer_id: str
    signals: tuple[Signal, ...]


@dataclass(frozen=True, slots=True)
class SignalContribution:
    analyzer_id: str
    signal_name: str
    raw_score: float
    confidence: float
    weight: float
    weighted_value: float


@dataclass(frozen=True, slots=True)
class FusedMoment:
    candidate: MomentCandidate
    score: float
    confidence: float
    contributions: tuple[SignalContribution, ...]


@dataclass(frozen=True, slots=True)
class Insight:
    insight_type: str
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class RankedMoment:
    candidate: MomentCandidate
    score: float
    confidence: float
    contributions: tuple[SignalContribution, ...]
    insights: tuple[Insight, ...]


@dataclass(frozen=True, slots=True)
class AnalyzerExecutionRecord:
    analyzer_id: str
    version: str
    status: AnalyzerExecutionStatus
    duration_ms: float
    cache_key: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class EngineResult:
    profile_id: str
    moments: tuple[RankedMoment, ...]
    executions: tuple[AnalyzerExecutionRecord, ...]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from backend.app.intelligence.models import AnalysisContext
from backend.app.services.scene_service import Scene
from backend.app.services.transcript_service import TranscriptSegment
from backend.app.services.video_service import VideoMetadata


@dataclass(frozen=True, slots=True)
class PrecomputedAnalysisInputs:
    source_fingerprint: str
    video_path: Path
    video_metadata: VideoMetadata
    scenes: tuple[Scene, ...]
    transcript_segments: tuple[TranscriptSegment, ...] = ()
    resources: Mapping[str, Any] = field(default_factory=dict)


class IntelligenceContextBuilder(ABC):
    @abstractmethod
    def build(self, inputs: PrecomputedAnalysisInputs) -> AnalysisContext:
        """Build the immutable context consumed by the MIE."""


class PrecomputedContextBuilder(IntelligenceContextBuilder):
    """Adapt existing pipeline outputs without coupling analyzers to their services."""

    def build(self, inputs: PrecomputedAnalysisInputs) -> AnalysisContext:
        return AnalysisContext(
            source_fingerprint=inputs.source_fingerprint,
            video_path=inputs.video_path,
            video_metadata=inputs.video_metadata,
            scenes=inputs.scenes,
            transcript_segments=inputs.transcript_segments,
            resources=inputs.resources,
        )

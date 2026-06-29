from backend.app.intelligence.analyzers.base import (
    SignalAnalyzer,
    deterministic_cache_key,
)
from backend.app.intelligence.models import (
    AnalysisContext,
    AnalyzerMetadata,
    EstimatedCost,
    MomentCandidate,
    Signal,
    SignalBatch,
)


class SceneStructureAnalyzer(SignalAnalyzer):
    def __init__(self, target_duration_seconds: float = 15.0) -> None:
        if target_duration_seconds <= 0:
            raise ValueError("target_duration_seconds must be positive")
        self._target_duration_seconds = target_duration_seconds
        self._metadata = AnalyzerMetadata(
            analyzer_id="scene_structure",
            version="1.0.0",
            priority=10,
            dependencies=(),
            estimated_cost=EstimatedCost.LOW,
            cacheable=True,
        )

    @property
    def metadata(self) -> AnalyzerMetadata:
        return self._metadata

    def cache_key(
        self,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
    ) -> str:
        return deterministic_cache_key(
            self.metadata,
            {
                "source_fingerprint": context.source_fingerprint,
                "target_duration_seconds": self._target_duration_seconds,
                "video_duration_seconds": context.video_metadata.duration_seconds,
                "candidates": [
                    [item.candidate_id, item.start_seconds, item.end_seconds]
                    for item in candidates
                ],
            },
        )

    async def analyze(
        self,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
    ) -> SignalBatch:
        video_duration = context.video_metadata.duration_seconds
        signals = []
        for candidate in candidates:
            duration_score = min(
                candidate.duration_seconds / self._target_duration_seconds,
                1.0,
            )
            midpoint = candidate.start_seconds + (candidate.duration_seconds / 2)
            position_score = max(0.0, min(1.0, 1.0 - (midpoint / video_duration)))
            signals.extend(
                (
                    Signal(
                        analyzer_id=self.metadata.analyzer_id,
                        candidate_id=candidate.candidate_id,
                        signal_name="scene.duration",
                        score=duration_score,
                        confidence=1.0,
                        evidence={
                            "duration_seconds": candidate.duration_seconds,
                            "target_duration_seconds": self._target_duration_seconds,
                        },
                    ),
                    Signal(
                        analyzer_id=self.metadata.analyzer_id,
                        candidate_id=candidate.candidate_id,
                        signal_name="scene.position",
                        score=position_score,
                        confidence=1.0,
                        evidence={
                            "midpoint_seconds": midpoint,
                            "video_duration_seconds": video_duration,
                        },
                    ),
                )
            )
        return SignalBatch(analyzer_id=self.metadata.analyzer_id, signals=tuple(signals))

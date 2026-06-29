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


class TranscriptActivityAnalyzer(SignalAnalyzer):
    def __init__(self, target_words_per_second: float = 2.5) -> None:
        if target_words_per_second <= 0:
            raise ValueError("target_words_per_second must be positive")
        self._target_words_per_second = target_words_per_second
        self._metadata = AnalyzerMetadata(
            analyzer_id="transcript_activity",
            version="1.0.0",
            priority=20,
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
                "target_words_per_second": self._target_words_per_second,
                "transcript": [
                    [item.start_seconds, item.end_seconds, item.text, item.scene_id]
                    for item in context.transcript_segments
                ],
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
        if not context.transcript_segments:
            return SignalBatch(analyzer_id=self.metadata.analyzer_id, signals=())

        signals = []
        for candidate in candidates:
            allocated_words = 0.0
            covered_seconds = 0.0
            matched_segments = 0

            for segment in context.transcript_segments:
                overlap = max(
                    0.0,
                    min(candidate.end_seconds, segment.end_seconds)
                    - max(candidate.start_seconds, segment.start_seconds),
                )
                if overlap <= 0:
                    continue
                segment_duration = segment.end_seconds - segment.start_seconds
                if segment_duration <= 0:
                    continue
                matched_segments += 1
                covered_seconds += overlap
                allocated_words += len(segment.text.split()) * (overlap / segment_duration)

            covered_seconds = min(covered_seconds, candidate.duration_seconds)
            words_per_second = allocated_words / candidate.duration_seconds
            density_score = min(words_per_second / self._target_words_per_second, 1.0)
            coverage_score = min(covered_seconds / candidate.duration_seconds, 1.0)
            signals.extend(
                (
                    Signal(
                        analyzer_id=self.metadata.analyzer_id,
                        candidate_id=candidate.candidate_id,
                        signal_name="transcript.word_density",
                        score=density_score,
                        confidence=1.0,
                        evidence={
                            "allocated_words": round(allocated_words, 3),
                            "words_per_second": round(words_per_second, 3),
                            "matched_segments": matched_segments,
                        },
                    ),
                    Signal(
                        analyzer_id=self.metadata.analyzer_id,
                        candidate_id=candidate.candidate_id,
                        signal_name="transcript.coverage",
                        score=coverage_score,
                        confidence=1.0,
                        evidence={
                            "covered_seconds": round(covered_seconds, 3),
                            "candidate_duration_seconds": candidate.duration_seconds,
                        },
                    ),
                )
            )
        return SignalBatch(analyzer_id=self.metadata.analyzer_id, signals=tuple(signals))

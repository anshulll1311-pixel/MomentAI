from backend.app.semantic.errors import SemanticValidationError
from backend.app.semantic.models import (
    ContextCompleteness,
    DeterministicInsight,
    SemanticContext,
    SemanticContribution,
    SemanticMomentContext,
    SemanticOptions,
)
from backend.app.services.moment_pipeline_service import AnalysisResult
from backend.app.services.transcript_service import TranscriptSegment


class SemanticContextBuilder:
    """Adapt one immutable AnalysisResult without invoking any analysis service."""

    def __init__(self, max_transcript_characters_per_moment: int = 4000) -> None:
        if max_transcript_characters_per_moment <= 0:
            raise ValueError("max transcript characters must be positive")
        self._max_transcript_characters = max_transcript_characters_per_moment

    def build(self, analysis: AnalysisResult, options: SemanticOptions) -> SemanticContext:
        ranked = analysis.engine_result.moments
        if not ranked:
            raise SemanticValidationError("AnalysisResult contains no ranked moments.")
        selected_ranks = options.selected_ranks or tuple(range(1, len(ranked) + 1))
        missing = tuple(rank for rank in selected_ranks if rank > len(ranked))
        if missing:
            values = ", ".join(str(rank) for rank in missing)
            raise SemanticValidationError(f"Selected semantic ranks do not exist: {values}.")

        segments = (
            analysis.transcript_result.segments
            if analysis.transcript_result is not None
            else ()
        )
        moments = []
        for rank in selected_ranks:
            moment = ranked[rank - 1]
            excerpt = _transcript_excerpt(
                segments,
                moment.candidate.start_seconds,
                moment.candidate.end_seconds,
                self._max_transcript_characters,
            )
            moments.append(
                SemanticMomentContext(
                    candidate_id=moment.candidate.candidate_id,
                    rank=rank,
                    start_seconds=moment.candidate.start_seconds,
                    end_seconds=moment.candidate.end_seconds,
                    scene_ids=moment.candidate.scene_ids,
                    deterministic_score=moment.score,
                    deterministic_confidence=moment.confidence,
                    transcript_excerpt=excerpt,
                    contributions=tuple(
                        SemanticContribution(
                            analyzer_id=item.analyzer_id,
                            signal_name=item.signal_name,
                            raw_score=item.raw_score,
                            confidence=item.confidence,
                            weight=item.weight,
                            weighted_value=item.weighted_value,
                        )
                        for item in moment.contributions
                    ),
                    deterministic_insights=tuple(
                        DeterministicInsight(
                            insight_type=item.insight_type,
                            summary=item.summary,
                            evidence=item.evidence,
                        )
                        for item in moment.insights
                    ),
                    context_completeness=(
                        ContextCompleteness.FULL
                        if excerpt is not None
                        else ContextCompleteness.REDUCED
                    ),
                )
            )

        metadata = analysis.video_metadata
        return SemanticContext(
            source_fingerprint=analysis.source_fingerprint,
            profile_id=analysis.engine_result.profile_id,
            video_duration_seconds=metadata.duration_seconds,
            width=metadata.width,
            height=metadata.height,
            language=(
                analysis.transcript_result.language
                if analysis.transcript_result is not None
                else None
            ),
            locale=options.locale,
            tone=options.tone,
            moments=tuple(moments),
        )


def _transcript_excerpt(
    segments: tuple[TranscriptSegment, ...],
    start_seconds: float,
    end_seconds: float,
    character_limit: int,
) -> str | None:
    excerpts = []
    for segment in segments:
        segment_start = segment.start_seconds
        segment_end = segment.end_seconds
        if min(end_seconds, segment_end) <= max(start_seconds, segment_start):
            continue
        text = segment.text.strip()
        if text:
            excerpts.append(f"[{segment_start:.3f}-{segment_end:.3f}] {text}")
    if not excerpts:
        return None
    combined = "\n".join(excerpts)
    if len(combined) <= character_limit:
        return combined
    return f"{combined[: max(0, character_limit - 1)].rstrip()}…"

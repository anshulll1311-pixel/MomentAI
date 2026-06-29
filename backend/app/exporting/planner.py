from backend.app.exporting.errors import ExportPlanningError
from backend.app.exporting.models import (
    ClipSpec,
    ContributionSnapshot,
    ExportOptions,
    InsightSnapshot,
)
from backend.app.services.moment_pipeline_service import AnalysisResult


class ExportPlanner:
    """Convert immutable ranked moments into media-only clip specifications."""

    def plan(
        self,
        analysis: AnalysisResult,
        options: ExportOptions,
    ) -> tuple[ClipSpec, ...]:
        moments = analysis.engine_result.moments
        if not moments:
            raise ExportPlanningError("No ranked moments are available for export.")

        selected_ranks = options.selected_ranks or tuple(
            range(1, min(options.top_k, len(moments)) + 1)
        )
        missing = [rank for rank in selected_ranks if rank > len(moments)]
        if missing:
            values = ", ".join(str(rank) for rank in missing)
            raise ExportPlanningError(f"Selected moment ranks do not exist: {values}.")

        duration = analysis.video_metadata.duration_seconds
        specs = []
        for rank in selected_ranks:
            moment = moments[rank - 1]
            start = max(0.0, moment.candidate.start_seconds - options.padding_before_seconds)
            end = min(duration, moment.candidate.end_seconds + options.padding_after_seconds)
            if end <= start:
                raise ExportPlanningError(f"Moment rank {rank} has an invalid export timeline.")
            specs.append(
                ClipSpec(
                    clip_id=f"moment-{rank:03d}",
                    candidate_id=moment.candidate.candidate_id,
                    rank=rank,
                    start_seconds=start,
                    end_seconds=end,
                    scene_ids=moment.candidate.scene_ids,
                    score=moment.score,
                    confidence=moment.confidence,
                    contributions=tuple(
                        ContributionSnapshot(
                            analyzer_id=item.analyzer_id,
                            signal_name=item.signal_name,
                            raw_score=item.raw_score,
                            confidence=item.confidence,
                            weight=item.weight,
                            weighted_value=item.weighted_value,
                        )
                        for item in moment.contributions
                    ),
                    insights=tuple(
                        InsightSnapshot(
                            insight_type=item.insight_type,
                            summary=item.summary,
                            evidence=item.evidence,
                        )
                        for item in moment.insights
                    ),
                )
            )
        return tuple(specs)

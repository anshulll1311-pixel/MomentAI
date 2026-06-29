from abc import ABC, abstractmethod

from backend.app.intelligence.models import AnalysisContext, FusedMoment, Insight
from backend.app.intelligence.profiles import RankingProfile


class InsightGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        moment: FusedMoment,
        context: AnalysisContext,
        profile: RankingProfile,
    ) -> tuple[Insight, ...]:
        """Generate explainable insights after fusion without changing engine APIs."""


class DeterministicInsightGenerator(InsightGenerator):
    def generate(
        self,
        moment: FusedMoment,
        context: AnalysisContext,
        profile: RankingProfile,
    ) -> tuple[Insight, ...]:
        if not moment.contributions:
            return (
                Insight(
                    insight_type="deterministic_summary",
                    summary="No enabled signal contributed to this candidate.",
                    evidence={"profile_id": profile.profile_id},
                ),
            )

        strongest = moment.contributions[:3]
        labels = ", ".join(
            f"{item.signal_name}={item.raw_score:.3f}" for item in strongest
        )
        return (
            Insight(
                insight_type="deterministic_summary",
                summary=f"Score {moment.score:.3f}; strongest signals: {labels}.",
                evidence={
                    "profile_id": profile.profile_id,
                    "source_fingerprint": context.source_fingerprint,
                    "contribution_count": len(moment.contributions),
                },
            ),
        )

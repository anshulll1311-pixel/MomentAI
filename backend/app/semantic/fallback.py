from backend.app.semantic.models import (
    CategoryPrediction,
    ContentOrigin,
    FallbackContent,
    SemanticMomentContext,
    SemanticMomentResult,
    SemanticMomentStatus,
)


class SemanticFallbackFactory:
    """Create explicitly labelled deterministic fallback content."""

    def content_for(self, moment: SemanticMomentContext) -> FallbackContent:
        explanation = (
            moment.deterministic_insights[0].summary
            if moment.deterministic_insights
            else "Deterministic ranking is available, but semantic enrichment is unavailable."
        )
        return FallbackContent(
            title=f"Moment {moment.rank}",
            description=None,
            hashtags=(),
            explanation=explanation,
            category=CategoryPrediction(
                category_id="unknown",
                label="Unknown",
                confidence=0.0,
            ),
            viral_potential=None,
        )

    def result_for(
        self,
        moment: SemanticMomentContext,
        status: SemanticMomentStatus = SemanticMomentStatus.DEGRADED,
    ) -> SemanticMomentResult:
        fallback = self.content_for(moment)
        return SemanticMomentResult(
            candidate_id=moment.candidate_id,
            rank=moment.rank,
            status=status,
            content_origin=ContentOrigin.DETERMINISTIC_FALLBACK,
            title=fallback.title,
            description=fallback.description,
            hashtags=fallback.hashtags,
            explanation=fallback.explanation,
            category=fallback.category,
            viral_potential=fallback.viral_potential,
            trace=None,
        )

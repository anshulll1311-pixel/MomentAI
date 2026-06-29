from abc import ABC, abstractmethod

from backend.app.intelligence.models import AnalysisContext, MomentCandidate


class CandidateGenerator(ABC):
    @abstractmethod
    def generate(self, context: AnalysisContext) -> tuple[MomentCandidate, ...]:
        """Generate deterministic moment candidates from an analysis context."""


class SceneCandidateGenerator(CandidateGenerator):
    def generate(self, context: AnalysisContext) -> tuple[MomentCandidate, ...]:
        return tuple(
            MomentCandidate(
                candidate_id=f"scene-{scene.id}",
                start_seconds=scene.start_seconds,
                end_seconds=scene.end_seconds,
                scene_ids=(scene.id,),
                attributes={"source": "scene"},
            )
            for scene in context.scenes
        )

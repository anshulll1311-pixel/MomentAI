from collections.abc import Iterable

from backend.app.intelligence.analyzers import (
    SceneStructureAnalyzer,
    SignalAnalyzer,
    TranscriptActivityAnalyzer,
)
from backend.app.intelligence.candidates import SceneCandidateGenerator
from backend.app.intelligence.engine import MomentIntelligenceEngine
from backend.app.intelligence.fusion import DeterministicWeightedFusion
from backend.app.intelligence.insights import DeterministicInsightGenerator
from backend.app.intelligence.policies import ExecutionPolicy
from backend.app.intelligence.profiles import (
    ProfileRegistry,
    RankingProfile,
    default_ranking_profile,
)
from backend.app.intelligence.registry import AnalyzerRegistry


def create_default_engine(
    additional_analyzers: Iterable[SignalAnalyzer] = (),
    additional_profiles: Iterable[RankingProfile] = (),
    execution_policy: ExecutionPolicy | None = None,
) -> MomentIntelligenceEngine:
    analyzers = AnalyzerRegistry(
        (
            SceneStructureAnalyzer(),
            TranscriptActivityAnalyzer(),
            *tuple(additional_analyzers),
        )
    )
    profiles = ProfileRegistry((default_ranking_profile(), *tuple(additional_profiles)))
    return MomentIntelligenceEngine(
        analyzer_registry=analyzers,
        profile_registry=profiles,
        candidate_generator=SceneCandidateGenerator(),
        fusion_strategy=DeterministicWeightedFusion(),
        insight_generator=DeterministicInsightGenerator(),
        execution_policy=execution_policy,
    )

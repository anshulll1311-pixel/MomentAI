import asyncio
import unittest
from pathlib import Path

from backend.app.intelligence.analyzers.base import SignalAnalyzer, deterministic_cache_key
from backend.app.intelligence.context import PrecomputedAnalysisInputs, PrecomputedContextBuilder
from backend.app.intelligence.factory import create_default_engine
from backend.app.intelligence.models import (
    AnalysisContext,
    AnalyzerExecutionStatus,
    AnalyzerMetadata,
    EstimatedCost,
    MomentCandidate,
    Signal,
    SignalBatch,
)
from backend.app.intelligence.profiles import RankingProfile, RankingThresholds
from backend.app.intelligence.policies import ExecutionPolicy
from backend.app.intelligence.registry import AnalyzerConfigurationError, AnalyzerRegistry
from backend.app.services.scene_service import Scene
from backend.app.services.transcript_service import TranscriptSegment
from backend.app.services.video_service import VideoMetadata


def make_context(fingerprint: str = "video-sha256") -> AnalysisContext:
    return AnalysisContext(
        source_fingerprint=fingerprint,
        video_path=Path("sample.mp4"),
        video_metadata=VideoMetadata(
            duration_seconds=20.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            bitrate=4_000_000,
            rotation=None,
            file_size_bytes=10_000_000,
        ),
        scenes=(
            Scene(1, 0.0, 5.0, 5.0, Path("scene-001.jpg")),
            Scene(2, 5.0, 20.0, 15.0, Path("scene-002.jpg")),
        ),
        transcript_segments=(
            TranscriptSegment(0.0, 4.0, "an energetic opening with several spoken words", 1),
            TranscriptSegment(8.0, 10.0, "short middle phrase", 2),
        ),
    )


class StubAnalyzer(SignalAnalyzer):
    def __init__(
        self,
        analyzer_id: str,
        dependencies: tuple[str, ...] = (),
        should_fail: bool = False,
        signal_score: float = 0.5,
        priority: int = 50,
        delay_seconds: float = 0.0,
    ) -> None:
        self.called = False
        self.should_fail = should_fail
        self.signal_score = signal_score
        self.delay_seconds = delay_seconds
        self._metadata = AnalyzerMetadata(
            analyzer_id=analyzer_id,
            version="1.0.0",
            priority=priority,
            dependencies=dependencies,
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
            [context.source_fingerprint, [item.candidate_id for item in candidates]],
        )

    async def analyze(
        self,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
    ) -> SignalBatch:
        self.called = True
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.should_fail:
            raise RuntimeError("intentional analyzer failure")
        return SignalBatch(
            analyzer_id=self.metadata.analyzer_id,
            signals=tuple(
                Signal(
                    analyzer_id=self.metadata.analyzer_id,
                    candidate_id=item.candidate_id,
                    signal_name=f"{self.metadata.analyzer_id}.score",
                    score=self.signal_score,
                    confidence=1.0,
                )
                for item in candidates
            ),
        )


class MomentIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_engine_returns_ranked_explainable_moments(self) -> None:
        result = await create_default_engine().analyze(make_context())

        self.assertEqual(result.profile_id, "default")
        self.assertEqual(len(result.moments), 2)
        self.assertEqual(len(result.executions), 2)
        self.assertTrue(
            all(item.status is AnalyzerExecutionStatus.SUCCESS for item in result.executions)
        )
        self.assertTrue(all(item.cache_key for item in result.executions))
        self.assertTrue(all(item.insights for item in result.moments))
        self.assertGreaterEqual(result.moments[0].score, result.moments[1].score)

    async def test_profile_changes_weights_without_engine_changes(self) -> None:
        podcast = RankingProfile(
            profile_id="podcast",
            weights={"transcript.coverage": 1.0},
            thresholds=RankingThresholds(),
        )
        engine = create_default_engine(additional_profiles=(podcast,))

        default_result = await engine.analyze(make_context(), "default")
        podcast_result = await engine.analyze(make_context(), "podcast")

        self.assertEqual(default_result.profile_id, "default")
        self.assertEqual(podcast_result.profile_id, "podcast")
        self.assertNotEqual(
            [item.score for item in default_result.moments],
            [item.score for item in podcast_result.moments],
        )

    async def test_failed_dependency_skips_dependent_analyzer(self) -> None:
        failed = StubAnalyzer("failed", should_fail=True)
        dependent = StubAnalyzer("dependent", dependencies=("failed",))
        profile = RankingProfile(
            profile_id="dependency-test",
            weights={"failed.score": 1.0, "dependent.score": 1.0},
            thresholds=RankingThresholds(),
        )
        engine = create_default_engine(
            additional_analyzers=(failed, dependent),
            additional_profiles=(profile,),
        )

        result = await engine.analyze(make_context(), "dependency-test")
        records = {item.analyzer_id: item for item in result.executions}

        self.assertEqual(records["failed"].status, AnalyzerExecutionStatus.FAILED)
        self.assertEqual(records["dependent"].status, AnalyzerExecutionStatus.SKIPPED)
        self.assertFalse(dependent.called)

    def test_cache_keys_are_deterministic_and_content_sensitive(self) -> None:
        analyzer = StubAnalyzer("cache-test")
        candidates = (
            MomentCandidate("scene-1", 0.0, 5.0, (1,)),
        )

        first = analyzer.cache_key(make_context("fingerprint-a"), candidates)
        repeated = analyzer.cache_key(make_context("fingerprint-a"), candidates)
        changed = analyzer.cache_key(make_context("fingerprint-b"), candidates)

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)
        self.assertTrue(analyzer.metadata.cacheable)

    def test_registry_rejects_missing_and_cyclic_dependencies(self) -> None:
        missing = AnalyzerRegistry((StubAnalyzer("child", dependencies=("missing",)),))
        with self.assertRaises(AnalyzerConfigurationError):
            missing.execution_layers()

        cyclic = AnalyzerRegistry(
            (
                StubAnalyzer("first", dependencies=("second",)),
                StubAnalyzer("second", dependencies=("first",)),
            )
        )
        with self.assertRaises(AnalyzerConfigurationError):
            cyclic.execution_layers()

    def test_registry_orders_independent_analyzers_by_priority(self) -> None:
        registry = AnalyzerRegistry(
            (
                StubAnalyzer("later", priority=100),
                StubAnalyzer("earlier", priority=5),
            )
        )

        first_layer = registry.execution_layers()[0]
        self.assertEqual(
            [item.metadata.analyzer_id for item in first_layer],
            ["earlier", "later"],
        )

    async def test_analyzer_timeout_is_isolated(self) -> None:
        slow = StubAnalyzer("slow", delay_seconds=0.05)
        profile = RankingProfile(
            profile_id="timeout-test",
            weights={"slow.score": 1.0},
            thresholds=RankingThresholds(),
        )
        engine = create_default_engine(
            additional_analyzers=(slow,),
            additional_profiles=(profile,),
            execution_policy=ExecutionPolicy(analyzer_timeouts={"slow": 0.001}),
        )

        result = await engine.analyze(make_context(), "timeout-test")
        record = next(item for item in result.executions if item.analyzer_id == "slow")

        self.assertEqual(record.status, AnalyzerExecutionStatus.FAILED)
        self.assertIn("TimeoutError", record.error or "")

    def test_metadata_contains_required_production_fields(self) -> None:
        metadata = StubAnalyzer("metadata-test").metadata

        self.assertEqual(metadata.analyzer_id, "metadata-test")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertEqual(metadata.priority, 50)
        self.assertEqual(metadata.dependencies, ())
        self.assertEqual(metadata.estimated_cost, EstimatedCost.LOW)
        self.assertTrue(metadata.cacheable)

    def test_context_builder_adapts_precomputed_pipeline_outputs(self) -> None:
        source = make_context()
        rebuilt = PrecomputedContextBuilder().build(
            PrecomputedAnalysisInputs(
                source_fingerprint=source.source_fingerprint,
                video_path=source.video_path,
                video_metadata=source.video_metadata,
                scenes=source.scenes,
                transcript_segments=source.transcript_segments,
                resources={"audio_features": "future-resource"},
            )
        )

        self.assertEqual(rebuilt.scenes, source.scenes)
        self.assertEqual(rebuilt.transcript_segments, source.transcript_segments)
        self.assertEqual(rebuilt.resources["audio_features"], "future-resource")


if __name__ == "__main__":
    unittest.main()

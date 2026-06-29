import asyncio
import logging
from time import perf_counter

from backend.app.intelligence.analyzers.base import SignalAnalyzer
from backend.app.intelligence.candidates import CandidateGenerator
from backend.app.intelligence.fusion import FusionStrategy
from backend.app.intelligence.insights import InsightGenerator
from backend.app.intelligence.models import (
    AnalysisContext,
    AnalyzerExecutionRecord,
    AnalyzerExecutionStatus,
    EngineResult,
    MomentCandidate,
    RankedMoment,
    SignalBatch,
)
from backend.app.intelligence.policies import ExecutionPolicy
from backend.app.intelligence.profiles import ProfileRegistry
from backend.app.intelligence.registry import AnalyzerRegistry

logger = logging.getLogger(__name__)


class MomentIntelligenceEngine:
    def __init__(
        self,
        analyzer_registry: AnalyzerRegistry,
        profile_registry: ProfileRegistry,
        candidate_generator: CandidateGenerator,
        fusion_strategy: FusionStrategy,
        insight_generator: InsightGenerator,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        self._analyzer_registry = analyzer_registry
        self._profile_registry = profile_registry
        self._candidate_generator = candidate_generator
        self._fusion_strategy = fusion_strategy
        self._insight_generator = insight_generator
        self._execution_policy = execution_policy or ExecutionPolicy()

    async def analyze(
        self,
        context: AnalysisContext,
        profile_id: str = "default",
    ) -> EngineResult:
        profile = self._profile_registry.get(profile_id)
        candidates = self._candidate_generator.generate(context)
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        records: dict[str, AnalyzerExecutionRecord] = {}
        batches: dict[str, SignalBatch] = {}
        record_order: list[str] = []

        for layer in self._analyzer_registry.execution_layers():
            runnable = []
            for analyzer in layer:
                metadata = analyzer.metadata
                failed_dependencies = [
                    dependency
                    for dependency in metadata.dependencies
                    if records[dependency].status is not AnalyzerExecutionStatus.SUCCESS
                ]
                if failed_dependencies:
                    dependency_list = ", ".join(failed_dependencies)
                    records[metadata.analyzer_id] = AnalyzerExecutionRecord(
                        analyzer_id=metadata.analyzer_id,
                        version=metadata.version,
                        status=AnalyzerExecutionStatus.SKIPPED,
                        duration_ms=0.0,
                        error=f"required dependencies did not succeed: {dependency_list}",
                    )
                    record_order.append(metadata.analyzer_id)
                else:
                    runnable.append(analyzer)

            results = await asyncio.gather(
                *(
                    self._execute_analyzer(analyzer, context, candidates, candidate_ids)
                    for analyzer in runnable
                )
            )
            for analyzer, (batch, record) in zip(runnable, results):
                analyzer_id = analyzer.metadata.analyzer_id
                records[analyzer_id] = record
                record_order.append(analyzer_id)
                if batch is not None:
                    batches[analyzer_id] = batch

        fused = self._fusion_strategy.fuse(
            candidates,
            tuple(batches[analyzer_id] for analyzer_id in record_order if analyzer_id in batches),
            profile,
        )
        moments = tuple(
            RankedMoment(
                candidate=moment.candidate,
                score=moment.score,
                confidence=moment.confidence,
                contributions=moment.contributions,
                insights=self._insight_generator.generate(moment, context, profile),
            )
            for moment in fused
        )
        return EngineResult(
            profile_id=profile.profile_id,
            moments=moments,
            executions=tuple(records[analyzer_id] for analyzer_id in record_order),
        )

    async def _execute_analyzer(
        self,
        analyzer: SignalAnalyzer,
        context: AnalysisContext,
        candidates: tuple[MomentCandidate, ...],
        candidate_ids: set[str],
    ) -> tuple[SignalBatch | None, AnalyzerExecutionRecord]:
        metadata = analyzer.metadata
        started = perf_counter()
        cache_key = None
        try:
            if metadata.cacheable:
                cache_key = analyzer.cache_key(context, candidates)
                if not cache_key:
                    raise ValueError("cacheable analyzer returned an empty cache key")
            batch = await asyncio.wait_for(
                analyzer.analyze(context, candidates),
                timeout=self._execution_policy.timeout_for(metadata.analyzer_id),
            )
            self._validate_batch(analyzer, batch, candidate_ids)
        except Exception as error:
            duration_ms = (perf_counter() - started) * 1000
            logger.warning(
                "MIE analyzer %s failed: %s",
                metadata.analyzer_id,
                error,
            )
            return None, AnalyzerExecutionRecord(
                analyzer_id=metadata.analyzer_id,
                version=metadata.version,
                status=AnalyzerExecutionStatus.FAILED,
                duration_ms=duration_ms,
                cache_key=cache_key,
                error=f"{type(error).__name__}: {error}",
            )

        duration_ms = (perf_counter() - started) * 1000
        return batch, AnalyzerExecutionRecord(
            analyzer_id=metadata.analyzer_id,
            version=metadata.version,
            status=AnalyzerExecutionStatus.SUCCESS,
            duration_ms=duration_ms,
            cache_key=cache_key,
        )

    @staticmethod
    def _validate_batch(
        analyzer: SignalAnalyzer,
        batch: SignalBatch,
        candidate_ids: set[str],
    ) -> None:
        analyzer_id = analyzer.metadata.analyzer_id
        if batch.analyzer_id != analyzer_id:
            raise ValueError("signal batch analyzer_id does not match its analyzer")
        seen_signals: set[tuple[str, str]] = set()
        for signal in batch.signals:
            if signal.analyzer_id != analyzer_id:
                raise ValueError("signal analyzer_id does not match its analyzer")
            if signal.candidate_id not in candidate_ids:
                raise ValueError(f"signal references unknown candidate: {signal.candidate_id}")
            signal_identity = (signal.candidate_id, signal.signal_name)
            if signal_identity in seen_signals:
                raise ValueError(
                    "signal batch contains a duplicate candidate and signal_name pair"
                )
            seen_signals.add(signal_identity)

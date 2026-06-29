import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from backend.app.semantic.batching import SemanticBatchPlanner
from backend.app.semantic.caching import (
    NoOpSemanticCache,
    SemanticCache,
    SemanticCacheKeyBuilder,
)
from backend.app.semantic.context import SemanticContextBuilder
from backend.app.semantic.errors import SemanticConfigurationError
from backend.app.semantic.fallback import SemanticFallbackFactory
from backend.app.semantic.models import (
    ContentOrigin,
    PromptTemplate,
    ProviderBatchRequest,
    ProviderFinishReason,
    ProviderMetadata,
    ProviderMomentOutput,
    ProviderTokenUsage,
    RenderedPrompt,
    SemanticCacheEntry,
    SemanticContext,
    SemanticDiagnostic,
    SemanticMomentContext,
    SemanticMomentResult,
    SemanticMomentStatus,
    SemanticOptions,
    SemanticResult,
    SemanticResultStatus,
    SemanticTrace,
)
from backend.app.semantic.prompts import (
    PromptRegistry,
    PromptRenderer,
    default_semantic_prompts,
)
from backend.app.semantic.providers import ProviderRegistry
from backend.app.semantic.validation import (
    SEMANTIC_RESPONSE_SCHEMA,
    SemanticOutputValidator,
)
from backend.app.semantic.versions import CATEGORY_TAXONOMY_VERSION, SEMANTIC_SCHEMA_VERSION
from backend.app.services.moment_pipeline_service import AnalysisResult


class SemanticIntelligenceService:
    """Optionally enrich one immutable AnalysisResult without re-running analysis."""

    def __init__(
        self,
        *,
        context_builder: SemanticContextBuilder,
        batch_planner: SemanticBatchPlanner,
        provider_registry: ProviderRegistry,
        prompt_registry: PromptRegistry,
        prompt_renderer: PromptRenderer,
        output_validator: SemanticOutputValidator,
        fallback_factory: SemanticFallbackFactory,
        cache: SemanticCache | None = None,
        cache_key_builder: SemanticCacheKeyBuilder | None = None,
        provider_timeout_seconds: float = 60.0,
    ) -> None:
        if provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be positive")
        self._context_builder = context_builder
        self._batch_planner = batch_planner
        self._provider_registry = provider_registry
        self._prompt_registry = prompt_registry
        self._prompt_renderer = prompt_renderer
        self._output_validator = output_validator
        self._fallback_factory = fallback_factory
        self._cache = cache or NoOpSemanticCache()
        self._cache_key_builder = cache_key_builder or SemanticCacheKeyBuilder()
        self._provider_timeout_seconds = provider_timeout_seconds

    async def enrich(
        self,
        analysis: AnalysisResult,
        options: SemanticOptions | None = None,
    ) -> SemanticResult:
        semantic_options = options or SemanticOptions()
        context = self._context_builder.build(analysis, semantic_options)
        diagnostics: list[SemanticDiagnostic] = []

        try:
            provider = self._provider_registry.resolve(semantic_options.provider_id)
            prompt = self._prompt_registry.get(
                semantic_options.prompt_id,
                semantic_options.prompt_version,
            )
            _validate_prompt_versions(prompt)
        except SemanticConfigurationError as error:
            diagnostics.append(
                SemanticDiagnostic(
                    stage="configuration",
                    status="degraded",
                    message=str(error),
                    provider_id=(
                        None
                        if semantic_options.provider_id == "auto"
                        else semantic_options.provider_id
                    ),
                )
            )
            return self._fallback_result(context, semantic_options, tuple(diagnostics))

        provider_metadata = provider.metadata
        cache_keys = {
            moment.candidate_id: self._cache_key_builder.build(
                source_fingerprint=context.source_fingerprint,
                moment=moment,
                options=semantic_options,
                prompt=prompt,
                provider=provider_metadata,
            )
            for moment in context.moments
        }
        cached_entries = {}
        try:
            cached_entries = dict(await self._cache.get_many(tuple(cache_keys.values())))
        except Exception as error:
            diagnostics.append(
                SemanticDiagnostic(
                    stage="cache",
                    status="warning",
                    message=f"Semantic cache lookup failed: {type(error).__name__}.",
                    provider_id=provider_metadata.provider_id,
                    retryable=True,
                )
            )

        results: dict[str, SemanticMomentResult] = {}
        cache_hits = 0
        misses = []
        for moment in context.moments:
            key = cache_keys[moment.candidate_id]
            entry = cached_entries.get(key)
            if entry is None or entry.key != key or entry.result.candidate_id != moment.candidate_id:
                misses.append(moment)
                continue
            cached_result = replace(
                entry.result,
                status=SemanticMomentStatus.CACHED,
                content_origin=ContentOrigin.CACHE,
                trace=(
                    replace(entry.result.trace, cached=True)
                    if entry.result.trace is not None
                    else None
                ),
            )
            results[moment.candidate_id] = cached_result
            cache_hits += 1

        try:
            batches = self._batch_planner.plan(
                context,
                provider_metadata,
                tuple(misses),
            )
        except Exception as error:
            diagnostics.append(
                SemanticDiagnostic(
                    stage="batching",
                    status="degraded",
                    message=f"Semantic batching failed: {type(error).__name__}.",
                    provider_id=provider_metadata.provider_id,
                )
            )
            for moment in misses:
                results[moment.candidate_id] = self._fallback_factory.result_for(moment)
            return _build_result(
                context=context,
                options=semantic_options,
                provider=provider_metadata,
                moments=_ordered_results(context, results),
                diagnostics=tuple(diagnostics),
                batch_count=0,
                cache_hits=cache_hits,
            )

        entries_to_cache: list[SemanticCacheEntry] = []
        for batch in batches:
            rendered: RenderedPrompt
            try:
                rendered = self._prompt_renderer.render(
                    template=prompt,
                    context=context,
                    batch=batch,
                    response_schema=SEMANTIC_RESPONSE_SCHEMA,
                )
            except Exception as error:
                diagnostics.append(
                    SemanticDiagnostic(
                        stage="prompt",
                        status="degraded",
                        message=f"Semantic prompt rendering failed: {type(error).__name__}.",
                        provider_id=provider_metadata.provider_id,
                    )
                )
                for moment in batch.moments:
                    results[moment.candidate_id] = self._fallback_factory.result_for(moment)
                continue

            request_id = f"sem_{uuid4().hex}"
            request = ProviderBatchRequest(
                request_id=request_id,
                source_fingerprint=context.source_fingerprint,
                batch=batch,
                prompt=rendered,
                response_schema=SEMANTIC_RESPONSE_SCHEMA,
                generation=semantic_options.generation,
            )
            started_at = datetime.now(UTC)
            started_timer = perf_counter()
            try:
                response = await asyncio.wait_for(
                    provider.generate_batch(request),
                    timeout=self._provider_timeout_seconds,
                )
            except Exception as error:
                diagnostics.append(
                    SemanticDiagnostic(
                        stage="provider",
                        status="degraded",
                        message=f"Semantic provider batch failed: {type(error).__name__}.",
                        provider_id=provider_metadata.provider_id,
                        retryable=isinstance(error, (TimeoutError, ConnectionError)),
                    )
                )
                for moment in batch.moments:
                    results[moment.candidate_id] = self._fallback_factory.result_for(moment)
                continue

            completed_at = datetime.now(UTC)
            latency_ms = (perf_counter() - started_timer) * 1000
            validation = self._output_validator.validate(
                response,
                tuple(moment.candidate_id for moment in batch.moments),
                provider_metadata.provider_id,
            )
            diagnostics.extend(validation.diagnostics)
            output_by_id = {
                output.candidate_id: output for output in validation.valid_outputs
            }
            for moment in batch.moments:
                output = output_by_id.get(moment.candidate_id)
                if output is None:
                    results[moment.candidate_id] = self._fallback_factory.result_for(moment)
                    continue
                trace = _trace_for(
                    request_id=request_id,
                    response_request_id=response.provider_request_id,
                    provider=provider_metadata,
                    prompt=rendered,
                    source_fingerprint=context.source_fingerprint,
                    input_hash=cache_keys[moment.candidate_id],
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                    token_usage=response.token_usage,
                    finish_reason=response.finish_reason,
                )
                result = _result_from_provider(moment, output, trace)
                results[moment.candidate_id] = result
                if result.status is SemanticMomentStatus.ENRICHED:
                    entries_to_cache.append(
                        SemanticCacheEntry(
                            key=cache_keys[moment.candidate_id],
                            result=result,
                            created_at=completed_at,
                        )
                    )

        if entries_to_cache:
            try:
                await self._cache.put_many(tuple(entries_to_cache))
            except Exception as error:
                diagnostics.append(
                    SemanticDiagnostic(
                        stage="cache",
                        status="warning",
                        message=f"Semantic cache write failed: {type(error).__name__}.",
                        provider_id=provider_metadata.provider_id,
                        retryable=True,
                    )
                )

        return _build_result(
            context=context,
            options=semantic_options,
            provider=provider_metadata,
            moments=_ordered_results(context, results),
            diagnostics=tuple(diagnostics),
            batch_count=len(batches),
            cache_hits=cache_hits,
        )

    def _fallback_result(
        self,
        context: SemanticContext,
        options: SemanticOptions,
        diagnostics: tuple[SemanticDiagnostic, ...],
    ) -> SemanticResult:
        return SemanticResult.create(
            status=SemanticResultStatus.DEGRADED,
            source_fingerprint=context.source_fingerprint,
            profile_id=context.profile_id,
            provider_id=None,
            model_id=None,
            prompt_id=options.prompt_id,
            prompt_version=options.prompt_version,
            batch_count=0,
            cache_hits=0,
            moments=tuple(
                self._fallback_factory.result_for(moment) for moment in context.moments
            ),
            diagnostics=diagnostics,
        )


def create_semantic_intelligence_service(
    provider_registry: ProviderRegistry,
    *,
    cache: SemanticCache | None = None,
    provider_timeout_seconds: float = 60.0,
) -> SemanticIntelligenceService:
    """Compose semantic generation around an application-supplied provider registry."""

    return SemanticIntelligenceService(
        context_builder=SemanticContextBuilder(),
        batch_planner=SemanticBatchPlanner(),
        provider_registry=provider_registry,
        prompt_registry=PromptRegistry(default_semantic_prompts()),
        prompt_renderer=PromptRenderer(),
        output_validator=SemanticOutputValidator(),
        fallback_factory=SemanticFallbackFactory(),
        cache=cache,
        provider_timeout_seconds=provider_timeout_seconds,
    )


def _validate_prompt_versions(prompt: PromptTemplate) -> None:
    if prompt.schema_version != SEMANTIC_SCHEMA_VERSION:
        raise SemanticConfigurationError(
            "Prompt schema version does not match the semantic output schema."
        )
    if prompt.category_taxonomy_version != CATEGORY_TAXONOMY_VERSION:
        raise SemanticConfigurationError(
            "Prompt category taxonomy version does not match the semantic taxonomy."
        )


def _result_from_provider(
    moment: SemanticMomentContext,
    output: ProviderMomentOutput,
    trace: SemanticTrace,
) -> SemanticMomentResult:
    if output.refused:
        return SemanticMomentResult(
            candidate_id=moment.candidate_id,
            rank=moment.rank,
            status=SemanticMomentStatus.REFUSED,
            content_origin=ContentOrigin.UNAVAILABLE,
            title=None,
            description=None,
            hashtags=(),
            explanation=None,
            category=None,
            viral_potential=None,
            trace=trace,
        )
    return SemanticMomentResult(
        candidate_id=moment.candidate_id,
        rank=moment.rank,
        status=SemanticMomentStatus.ENRICHED,
        content_origin=ContentOrigin.AI,
        title=output.title,
        description=output.description,
        hashtags=output.hashtags,
        explanation=output.explanation,
        category=output.category,
        viral_potential=output.viral_potential,
        trace=trace,
    )


def _trace_for(
    *,
    request_id: str,
    response_request_id: str | None,
    provider: ProviderMetadata,
    prompt: RenderedPrompt,
    source_fingerprint: str,
    input_hash: str,
    started_at: datetime,
    completed_at: datetime,
    latency_ms: float,
    token_usage: ProviderTokenUsage,
    finish_reason: ProviderFinishReason,
) -> SemanticTrace:
    return SemanticTrace(
        request_id=request_id,
        provider_request_id=response_request_id,
        provider_id=provider.provider_id,
        adapter_version=provider.adapter_version,
        model_id=provider.model_id,
        model_version=provider.model_version,
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.prompt_version,
        prompt_hash=prompt.rendered_hash,
        source_fingerprint=source_fingerprint,
        input_hash=input_hash,
        cached=False,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        token_usage=token_usage,
        finish_reason=finish_reason,
    )


def _ordered_results(
    context: SemanticContext,
    results: dict[str, SemanticMomentResult],
) -> tuple[SemanticMomentResult, ...]:
    return tuple(results[moment.candidate_id] for moment in context.moments)


def _build_result(
    *,
    context: SemanticContext,
    options: SemanticOptions,
    provider: ProviderMetadata,
    moments: tuple[SemanticMomentResult, ...],
    diagnostics: tuple[SemanticDiagnostic, ...],
    batch_count: int,
    cache_hits: int,
) -> SemanticResult:
    successful = sum(
        moment.status in (SemanticMomentStatus.ENRICHED, SemanticMomentStatus.CACHED)
        for moment in moments
    )
    if successful == len(moments):
        status = SemanticResultStatus.COMPLETE
    elif successful == 0:
        status = SemanticResultStatus.DEGRADED
    else:
        status = SemanticResultStatus.PARTIAL
    return SemanticResult.create(
        status=status,
        source_fingerprint=context.source_fingerprint,
        profile_id=context.profile_id,
        provider_id=provider.provider_id,
        model_id=provider.model_id,
        prompt_id=options.prompt_id,
        prompt_version=options.prompt_version,
        batch_count=batch_count,
        cache_hits=cache_hits,
        moments=moments,
        diagnostics=diagnostics,
    )

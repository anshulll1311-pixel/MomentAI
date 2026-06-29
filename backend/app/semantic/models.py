"""Immutable domain contracts shared by semantic foundation components."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.app.semantic.versions import (
    CATEGORY_TAXONOMY_VERSION,
    DEFAULT_PROMPT_ID,
    DEFAULT_PROMPT_VERSION,
    SEMANTIC_LAYER_VERSION,
    SEMANTIC_SCHEMA_VERSION,
)


class SemanticResultStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    DEGRADED = "degraded"


class SemanticMomentStatus(StrEnum):
    ENRICHED = "enriched"
    CACHED = "cached"
    DEGRADED = "degraded"
    REFUSED = "refused"


class ContentOrigin(StrEnum):
    AI = "ai"
    CACHE = "cache"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    UNAVAILABLE = "unavailable"


class ContextCompleteness(StrEnum):
    FULL = "full"
    REDUCED = "reduced"


class ProviderFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    SAFETY = "safety"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GenerationParameters:
    temperature: float = 0.2
    max_output_tokens: int = 2048
    top_p: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be greater than 0 and at most 1")


@dataclass(frozen=True, slots=True)
class SemanticOptions:
    """Provider-neutral options for one semantic enrichment run."""

    provider_id: str = "auto"
    locale: str = "en"
    tone: str = "neutral"
    selected_ranks: tuple[int, ...] = ()
    prompt_id: str = DEFAULT_PROMPT_ID
    prompt_version: str = DEFAULT_PROMPT_VERSION
    generation: GenerationParameters = field(default_factory=GenerationParameters)

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_id", self.provider_id),
            ("locale", self.locale),
            ("tone", self.tone),
            ("prompt_id", self.prompt_id),
            ("prompt_version", self.prompt_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if any(rank <= 0 for rank in self.selected_ranks):
            raise ValueError("selected_ranks must contain positive integers")
        if len(set(self.selected_ranks)) != len(self.selected_ranks):
            raise ValueError("selected_ranks cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class SemanticContribution:
    analyzer_id: str
    signal_name: str
    raw_score: float
    confidence: float
    weight: float
    weighted_value: float


@dataclass(frozen=True, slots=True)
class DeterministicInsight:
    insight_type: str
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class SemanticMomentContext:
    candidate_id: str
    rank: int
    start_seconds: float
    end_seconds: float
    scene_ids: tuple[int, ...]
    deterministic_score: float
    deterministic_confidence: float
    transcript_excerpt: str | None
    contributions: tuple[SemanticContribution, ...]
    deterministic_insights: tuple[DeterministicInsight, ...]
    context_completeness: ContextCompleteness

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id cannot be empty")
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("semantic moment timeline is invalid")

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class SemanticContext:
    """Provider-neutral snapshot derived from one immutable AnalysisResult."""

    source_fingerprint: str
    profile_id: str
    video_duration_seconds: float
    width: int
    height: int
    language: str | None
    locale: str
    tone: str
    moments: tuple[SemanticMomentContext, ...]

    def __post_init__(self) -> None:
        if not self.source_fingerprint.strip() or not self.profile_id.strip():
            raise ValueError("source_fingerprint and profile_id are required")
        if not self.moments:
            raise ValueError("semantic context requires at least one moment")


@dataclass(frozen=True, slots=True)
class SemanticBatch:
    batch_id: str
    moments: tuple[SemanticMomentContext, ...]
    estimated_input_tokens: int

    def __post_init__(self) -> None:
        if not self.batch_id.strip() or not self.moments:
            raise ValueError("semantic batch ID and moments are required")
        if self.estimated_input_tokens <= 0:
            raise ValueError("estimated_input_tokens must be positive")


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Capabilities and version identity exposed by a provider adapter."""

    provider_id: str
    adapter_version: str
    model_id: str
    model_version: str | None
    max_batch_size: int
    max_input_tokens: int
    supports_structured_output: bool
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.adapter_version.strip() or not self.model_id.strip():
            raise ValueError("provider ID, adapter version, and model ID are required")
        if self.max_batch_size <= 0 or self.max_input_tokens <= 0:
            raise ValueError("provider batch and token limits must be positive")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Immutable, explicitly versioned provider-neutral prompt template."""

    prompt_id: str
    version: str
    schema_version: str
    category_taxonomy_version: str
    system_template: str
    user_template: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.prompt_id,
                self.version,
                self.schema_version,
                self.category_taxonomy_version,
                self.system_template,
                self.user_template,
            )
        ):
            raise ValueError("prompt template fields cannot be empty")

    @property
    def content_hash(self) -> str:
        material = "\n".join(
            (
                self.prompt_id,
                self.version,
                self.schema_version,
                self.category_taxonomy_version,
                self.system_template,
                self.user_template,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    prompt_id: str
    prompt_version: str
    schema_version: str
    template_hash: str
    system_message: str
    user_message: str
    rendered_hash: str


@dataclass(frozen=True, slots=True)
class ProviderBatchRequest:
    """One structured request containing multiple ranked moments."""

    request_id: str
    source_fingerprint: str
    batch: SemanticBatch
    prompt: RenderedPrompt
    response_schema: Mapping[str, Any]
    generation: GenerationParameters

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id cannot be empty")
        object.__setattr__(self, "response_schema", MappingProxyType(dict(self.response_schema)))


@dataclass(frozen=True, slots=True)
class CategoryPrediction:
    category_id: str
    label: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ViralPotential:
    score: float
    confidence: float
    rationale: str
    limitations: str


@dataclass(frozen=True, slots=True)
class ProviderMomentOutput:
    candidate_id: str
    title: str | None
    description: str | None
    hashtags: tuple[str, ...]
    explanation: str | None
    category: CategoryPrediction | None
    viral_potential: ViralPotential | None
    refused: bool = False


@dataclass(frozen=True, slots=True)
class ProviderTokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderBatchResponse:
    """Provider-neutral batch response before validation."""

    outputs: tuple[ProviderMomentOutput, ...]
    provider_request_id: str | None = None
    token_usage: ProviderTokenUsage = field(default_factory=ProviderTokenUsage)
    finish_reason: ProviderFinishReason = ProviderFinishReason.UNKNOWN
    raw_response_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticTrace:
    request_id: str
    provider_request_id: str | None
    provider_id: str
    adapter_version: str
    model_id: str
    model_version: str | None
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    source_fingerprint: str
    input_hash: str
    cached: bool
    started_at: datetime
    completed_at: datetime
    latency_ms: float
    token_usage: ProviderTokenUsage
    finish_reason: ProviderFinishReason


@dataclass(frozen=True, slots=True)
class SemanticMomentResult:
    candidate_id: str
    rank: int
    status: SemanticMomentStatus
    content_origin: ContentOrigin
    title: str | None
    description: str | None
    hashtags: tuple[str, ...]
    explanation: str | None
    category: CategoryPrediction | None
    viral_potential: ViralPotential | None
    trace: SemanticTrace | None = None


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    stage: str
    status: str
    message: str
    candidate_id: str | None = None
    provider_id: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid_outputs: tuple[ProviderMomentOutput, ...]
    invalid_candidate_ids: tuple[str, ...]
    diagnostics: tuple[SemanticDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class FallbackContent:
    title: str
    description: str | None
    hashtags: tuple[str, ...]
    explanation: str | None
    category: CategoryPrediction
    viral_potential: ViralPotential | None


@dataclass(frozen=True, slots=True)
class SemanticCacheEntry:
    key: str
    result: SemanticMomentResult
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """Versioned semantic output that preserves deterministic moment order."""

    status: SemanticResultStatus
    semantic_layer_version: str
    schema_version: str
    category_taxonomy_version: str
    source_fingerprint: str
    profile_id: str
    provider_id: str | None
    model_id: str | None
    prompt_id: str
    prompt_version: str
    batch_count: int
    cache_hits: int
    moments: tuple[SemanticMomentResult, ...]
    diagnostics: tuple[SemanticDiagnostic, ...]

    @classmethod
    def create(
        cls,
        *,
        status: SemanticResultStatus,
        source_fingerprint: str,
        profile_id: str,
        provider_id: str | None,
        model_id: str | None,
        prompt_id: str,
        prompt_version: str,
        batch_count: int,
        cache_hits: int,
        moments: tuple[SemanticMomentResult, ...],
        diagnostics: tuple[SemanticDiagnostic, ...],
    ) -> "SemanticResult":
        return cls(
            status=status,
            semantic_layer_version=SEMANTIC_LAYER_VERSION,
            schema_version=SEMANTIC_SCHEMA_VERSION,
            category_taxonomy_version=CATEGORY_TAXONOMY_VERSION,
            source_fingerprint=source_fingerprint,
            profile_id=profile_id,
            provider_id=provider_id,
            model_id=model_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            batch_count=batch_count,
            cache_hits=cache_hits,
            moments=moments,
            diagnostics=diagnostics,
        )

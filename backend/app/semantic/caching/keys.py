import hashlib
import json
from typing import Any

from backend.app.semantic.models import (
    PromptTemplate,
    ProviderMetadata,
    SemanticMomentContext,
    SemanticOptions,
)
from backend.app.semantic.versions import CATEGORY_TAXONOMY_VERSION, SEMANTIC_SCHEMA_VERSION


class SemanticCacheKeyBuilder:
    """Build deterministic, content-sensitive, per-moment semantic cache keys."""

    def build(
        self,
        *,
        source_fingerprint: str,
        moment: SemanticMomentContext,
        options: SemanticOptions,
        prompt: PromptTemplate,
        provider: ProviderMetadata,
    ) -> str:
        material: dict[str, Any] = {
            "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
            "category_taxonomy_version": CATEGORY_TAXONOMY_VERSION,
            "source_fingerprint": source_fingerprint,
            "candidate_id": moment.candidate_id,
            "timeline": [moment.start_seconds, moment.end_seconds],
            "transcript_excerpt": moment.transcript_excerpt,
            "deterministic_score": moment.deterministic_score,
            "deterministic_confidence": moment.deterministic_confidence,
            "contributions": [
                [
                    item.analyzer_id,
                    item.signal_name,
                    item.raw_score,
                    item.confidence,
                    item.weight,
                    item.weighted_value,
                ]
                for item in moment.contributions
            ],
            "insights": [
                [item.insight_type, item.summary, dict(item.evidence)]
                for item in moment.deterministic_insights
            ],
            "locale": options.locale,
            "tone": options.tone,
            "generation": {
                "temperature": options.generation.temperature,
                "max_output_tokens": options.generation.max_output_tokens,
                "top_p": options.generation.top_p,
            },
            "prompt": [prompt.prompt_id, prompt.version, prompt.content_hash],
            "provider": [
                provider.provider_id,
                provider.adapter_version,
                provider.model_id,
                provider.model_version,
            ],
        }
        canonical = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return f"semantic:v1:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

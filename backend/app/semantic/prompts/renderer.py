import hashlib
import json
from typing import Any, Mapping

from backend.app.semantic.errors import PromptRenderError
from backend.app.semantic.models import (
    PromptTemplate,
    RenderedPrompt,
    SemanticBatch,
    SemanticContext,
)

CONTEXT_PLACEHOLDER = "{{semantic_context_json}}"
SCHEMA_PLACEHOLDER = "{{response_schema_json}}"


class PromptRenderer:
    """Render provider-neutral prompts from canonical, untrusted context JSON."""

    def render(
        self,
        *,
        template: PromptTemplate,
        context: SemanticContext,
        batch: SemanticBatch,
        response_schema: Mapping[str, Any],
    ) -> RenderedPrompt:
        if CONTEXT_PLACEHOLDER not in template.user_template:
            raise PromptRenderError(
                f"Prompt must contain the context placeholder: {CONTEXT_PLACEHOLDER}."
            )
        if SCHEMA_PLACEHOLDER not in template.user_template:
            raise PromptRenderError(
                f"Prompt must contain the schema placeholder: {SCHEMA_PLACEHOLDER}."
            )
        context_json = json.dumps(
            _context_payload(context, batch),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        schema_json = json.dumps(
            dict(response_schema),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        user_message = template.user_template.replace(
            CONTEXT_PLACEHOLDER,
            context_json,
        ).replace(SCHEMA_PLACEHOLDER, schema_json)
        rendered_hash = hashlib.sha256(
            f"{template.system_template}\n{user_message}".encode("utf-8")
        ).hexdigest()
        return RenderedPrompt(
            prompt_id=template.prompt_id,
            prompt_version=template.version,
            schema_version=template.schema_version,
            template_hash=template.content_hash,
            system_message=template.system_template,
            user_message=user_message,
            rendered_hash=rendered_hash,
        )


def _context_payload(context: SemanticContext, batch: SemanticBatch) -> dict[str, Any]:
    return {
        "source_fingerprint": context.source_fingerprint,
        "profile_id": context.profile_id,
        "video": {
            "duration_seconds": context.video_duration_seconds,
            "width": context.width,
            "height": context.height,
            "language": context.language,
        },
        "locale": context.locale,
        "tone": context.tone,
        "batch_id": batch.batch_id,
        "moments": [
            {
                "candidate_id": moment.candidate_id,
                "rank": moment.rank,
                "start_seconds": moment.start_seconds,
                "end_seconds": moment.end_seconds,
                "scene_ids": list(moment.scene_ids),
                "deterministic_score": moment.deterministic_score,
                "deterministic_confidence": moment.deterministic_confidence,
                "transcript_excerpt": moment.transcript_excerpt,
                "context_completeness": str(moment.context_completeness),
                "contributions": [
                    {
                        "analyzer_id": item.analyzer_id,
                        "signal_name": item.signal_name,
                        "raw_score": item.raw_score,
                        "confidence": item.confidence,
                        "weight": item.weight,
                        "weighted_value": item.weighted_value,
                    }
                    for item in moment.contributions
                ],
                "deterministic_insights": [
                    {
                        "insight_type": item.insight_type,
                        "summary": item.summary,
                        "evidence": dict(item.evidence),
                    }
                    for item in moment.deterministic_insights
                ],
            }
            for moment in batch.moments
        ],
    }

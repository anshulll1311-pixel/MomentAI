from types import MappingProxyType
from typing import Any, Mapping

from backend.app.semantic.models import (
    CategoryPrediction,
    ProviderBatchResponse,
    ProviderMomentOutput,
    SemanticDiagnostic,
    ValidationResult,
    ViralPotential,
)

DEFAULT_CATEGORY_TAXONOMY: Mapping[str, str] = MappingProxyType(
    {
        "animals": "Animals",
        "comedy": "Comedy",
        "education": "Education",
        "entertainment": "Entertainment",
        "gaming": "Gaming",
        "lifestyle": "Lifestyle",
        "music": "Music",
        "news": "News",
        "other": "Other",
        "podcast": "Podcast",
        "sports": "Sports",
        "unknown": "Unknown",
    }
)

SEMANTIC_RESPONSE_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "required": ["moments"],
        "additionalProperties": False,
        "properties": {
            "moments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": [
                        "candidate_id",
                        "title",
                        "description",
                        "hashtags",
                        "explanation",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "candidate_id": {"type": "string", "minLength": 1},
                        "title": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                        },
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "hashtags": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "explanation": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                    },
                },
            }
        },
    }
)


class SemanticOutputValidator:
    """Validate and normalize untrusted provider output per moment."""

    def __init__(
        self,
        category_taxonomy: Mapping[str, str] = DEFAULT_CATEGORY_TAXONOMY,
        max_title_characters: int = 120,
        max_description_characters: int = 1000,
        max_explanation_characters: int = 1000,
        max_hashtags: int = 10,
    ) -> None:
        if not category_taxonomy:
            raise ValueError("category taxonomy cannot be empty")
        if min(
            max_title_characters,
            max_description_characters,
            max_explanation_characters,
            max_hashtags,
        ) <= 0:
            raise ValueError("semantic validation limits must be positive")
        self._categories = dict(category_taxonomy)
        self._max_title = max_title_characters
        self._max_description = max_description_characters
        self._max_explanation = max_explanation_characters
        self._max_hashtags = max_hashtags

    def validate(
        self,
        response: ProviderBatchResponse,
        expected_candidate_ids: tuple[str, ...],
        provider_id: str,
    ) -> ValidationResult:
        expected = set(expected_candidate_ids)
        valid: list[ProviderMomentOutput] = []
        invalid: set[str] = set()
        diagnostics: list[SemanticDiagnostic] = []
        seen: set[str] = set()

        for output in response.outputs:
            candidate_id = output.candidate_id
            if candidate_id not in expected:
                diagnostics.append(
                    _diagnostic(
                        "Provider returned an unknown candidate ID.",
                        candidate_id,
                        provider_id,
                    )
                )
                continue
            if candidate_id in seen:
                invalid.add(candidate_id)
                diagnostics.append(
                    _diagnostic(
                        "Provider returned a duplicate candidate ID.",
                        candidate_id,
                        provider_id,
                    )
                )
                continue
            seen.add(candidate_id)
            if output.refused:
                valid.append(output)
                continue
            try:
                valid.append(self._normalize(output))
            except (TypeError, ValueError) as error:
                invalid.add(candidate_id)
                diagnostics.append(_diagnostic(str(error), candidate_id, provider_id))

        for candidate_id in expected_candidate_ids:
            if candidate_id not in seen:
                invalid.add(candidate_id)
                diagnostics.append(
                    _diagnostic(
                        "Provider response omitted the requested candidate.",
                        candidate_id,
                        provider_id,
                    )
                )

        valid = [output for output in valid if output.candidate_id not in invalid]
        return ValidationResult(
            valid_outputs=tuple(valid),
            invalid_candidate_ids=tuple(
                candidate_id for candidate_id in expected_candidate_ids if candidate_id in invalid
            ),
            diagnostics=tuple(diagnostics),
        )

    def _normalize(self, output: ProviderMomentOutput) -> ProviderMomentOutput:
        title = _required_text(output.title, "title", self._max_title)
        description = _required_text(
            output.description,
            "description",
            self._max_description,
        )
        explanation = _required_text(
            output.explanation,
            "explanation",
            self._max_explanation,
        )
        if len(output.hashtags) > self._max_hashtags:
            raise ValueError("Provider returned too many hashtags.")
        hashtags = tuple(_normalize_hashtag(value) for value in output.hashtags)
        if len(hashtags) != len(set(tag.lower() for tag in hashtags)):
            raise ValueError("Provider returned duplicate hashtags.")
        category = None
        if output.category is not None:
            category_id = output.category.category_id.strip().lower()
            if category_id not in self._categories:
                raise ValueError(f"Provider returned an unknown category: {category_id}.")
            _unit_interval(output.category.confidence, "category confidence")
            category = CategoryPrediction(
                category_id=category_id,
                label=self._categories[category_id],
                confidence=output.category.confidence,
            )
        viral = (
            _validated_viral(output.viral_potential)
            if output.viral_potential is not None
            else None
        )
        return ProviderMomentOutput(
            candidate_id=output.candidate_id,
            title=title,
            description=description,
            hashtags=hashtags,
            explanation=explanation,
            category=category,
            viral_potential=viral,
            refused=False,
        )


def _required_text(value: str | None, name: str, maximum: int) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"Provider output is missing {name}.")
    if len(normalized) > maximum:
        raise ValueError(f"Provider {name} exceeds {maximum} characters.")
    return normalized


def _normalize_hashtag(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Provider returned an empty hashtag.")
    if any(character.isspace() for character in normalized):
        raise ValueError("Provider hashtags cannot contain whitespace.")
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"
    if len(normalized) > 80:
        raise ValueError("Provider hashtag exceeds 80 characters.")
    return normalized


def _validated_viral(value: ViralPotential) -> ViralPotential:
    _unit_interval(value.score, "viral potential score")
    _unit_interval(value.confidence, "viral potential confidence")
    rationale = _required_text(value.rationale, "viral rationale", 1000)
    limitations = _required_text(value.limitations, "viral limitations", 1000)
    return ViralPotential(
        score=value.score,
        confidence=value.confidence,
        rationale=rationale,
        limitations=limitations,
    )


def _unit_interval(value: float, name: str) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"Provider {name} must be between 0 and 1.")


def _diagnostic(
    message: str,
    candidate_id: str,
    provider_id: str,
) -> SemanticDiagnostic:
    return SemanticDiagnostic(
        stage="validation",
        status="degraded",
        message=message,
        candidate_id=candidate_id,
        provider_id=provider_id,
    )

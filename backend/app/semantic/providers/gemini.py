"""Google Gemini transport adapter for provider-neutral semantic batches."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol, cast

from pydantic import SecretStr

from backend.app.semantic.errors import (
    ProviderExecutionError,
    ProviderTimeoutError,
    SemanticConfigurationError,
)
from backend.app.semantic.models import (
    CategoryPrediction,
    ProviderBatchRequest,
    ProviderBatchResponse,
    ProviderFinishReason,
    ProviderMetadata,
    ProviderMomentOutput,
    ProviderTokenUsage,
    ViralPotential,
)
from backend.app.semantic.providers.base import (
    BaseAIProvider,
    ProviderDiagnosticSink,
    ProviderRequestDiagnostic,
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = (408, 429, 500, 502, 503, 504)
_SAFETY_FINISH_REASONS = frozenset(
    {
        "BLOCKLIST",
        "IMAGE_SAFETY",
        "PROHIBITED_CONTENT",
        "RECITATION",
        "SAFETY",
        "SPII",
    }
)


class _AsyncModels(Protocol):
    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: Mapping[str, Any],
    ) -> Any: ...


class _AsyncClient(Protocol):
    models: _AsyncModels

    async def aclose(self) -> None: ...


class _GeminiClient(Protocol):
    aio: _AsyncClient

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class GeminiRetryPolicy:
    """Retry settings passed directly to the Google Gen AI SDK."""

    attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    status_codes: tuple[int, ...] = _RETRYABLE_STATUS_CODES

    def __post_init__(self) -> None:
        if self.attempts <= 0:
            raise ValueError("Gemini retry attempts must be positive")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("Gemini retry delays cannot be negative")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("Gemini maximum retry delay cannot be less than initial delay")
        if self.exponential_base < 1:
            raise ValueError("Gemini retry exponential base must be at least 1")
        if self.jitter < 0:
            raise ValueError("Gemini retry jitter cannot be negative")
        if not self.status_codes or any(code < 100 or code > 599 for code in self.status_codes):
            raise ValueError("Gemini retry status codes must be valid HTTP status codes")

    def as_sdk_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "initial_delay": self.initial_delay_seconds,
            "max_delay": self.max_delay_seconds,
            "exp_base": self.exponential_base,
            "jitter": self.jitter,
            "http_status_codes": list(self.status_codes),
        }


@dataclass(frozen=True, slots=True)
class GeminiSafetySetting:
    """One SDK-native Gemini harm category and blocking threshold pair."""

    category: str
    threshold: str

    def __post_init__(self) -> None:
        if not self.category.strip() or not self.threshold.strip():
            raise ValueError("Gemini safety category and threshold cannot be empty")

    def as_sdk_dict(self) -> dict[str, str]:
        return {"category": self.category, "threshold": self.threshold}


@dataclass(frozen=True, slots=True)
class GeminiProviderConfig:
    """Explicit application configuration for one Gemini provider instance."""

    api_key: SecretStr
    model_id: str
    model_version: str | None = None
    adapter_version: str = "1.0.0"
    timeout_seconds: float = 60.0
    max_batch_size: int = 20
    max_input_tokens: int = 1_000_000
    retry_policy: GeminiRetryPolicy = field(default_factory=GeminiRetryPolicy)
    safety_settings: tuple[GeminiSafetySetting, ...] = ()

    def __post_init__(self) -> None:
        if not self.api_key.get_secret_value().strip():
            raise ValueError("Gemini API key cannot be empty")
        if not self.model_id.strip() or not self.adapter_version.strip():
            raise ValueError("Gemini model ID and adapter version are required")
        if self.timeout_seconds <= 0:
            raise ValueError("Gemini timeout must be positive")
        if self.max_batch_size <= 0 or self.max_input_tokens <= 0:
            raise ValueError("Gemini batch and token limits must be positive")


class GeminiProvider(BaseAIProvider):
    """Official Google Gen AI SDK adapter with structured JSON responses."""

    def __init__(
        self,
        config: GeminiProviderConfig,
        *,
        client: _GeminiClient | None = None,
        diagnostic_sink: ProviderDiagnosticSink | None = None,
    ) -> None:
        self._config = config
        self._client = client or _create_google_client(config)
        self._owns_client = client is None
        self._diagnostic_sink = diagnostic_sink
        self._metadata = ProviderMetadata(
            provider_id="gemini",
            adapter_version=config.adapter_version,
            model_id=config.model_id,
            model_version=config.model_version,
            max_batch_size=config.max_batch_size,
            max_input_tokens=config.max_input_tokens,
            supports_structured_output=True,
            capabilities=(
                "batch",
                "request_tracing",
                "safety_controls",
                "structured_json",
                "token_usage",
            ),
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def generate_batch(self, request: ProviderBatchRequest) -> ProviderBatchResponse:
        """Send one rendered batch and adapt the SDK response to domain models."""

        started = monotonic()
        logger.info(
            "Gemini request started request_id=%s model_id=%s batch_size=%d",
            request.request_id,
            self.metadata.model_id,
            len(request.batch.moments),
        )
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                sdk_response = await self._client.aio.models.generate_content(
                    model=self.metadata.model_id,
                    contents=request.prompt.user_message,
                    config=self._generation_config(request),
                )
            response = _adapt_response(sdk_response, request)
        except TimeoutError as error:
            latency_ms = _latency_ms(started)
            self._emit_diagnostic(
                request=request,
                status="timed_out",
                latency_ms=latency_ms,
                error_type=type(error).__name__,
                retryable=True,
            )
            logger.warning(
                "Gemini request timed out request_id=%s latency_ms=%.2f",
                request.request_id,
                latency_ms,
            )
            raise ProviderTimeoutError(
                f"Gemini request {request.request_id} exceeded the configured timeout."
            ) from error
        except ProviderExecutionError as error:
            self._record_failure(request, started, error)
            raise
        except Exception as error:
            self._record_failure(request, started, error)
            raise ProviderExecutionError(
                f"Gemini request {request.request_id} failed with {type(error).__name__}."
            ) from error

        latency_ms = _latency_ms(started)
        self._emit_diagnostic(
            request=request,
            status="succeeded",
            latency_ms=latency_ms,
            provider_request_id=response.provider_request_id,
            token_usage=response.token_usage,
            finish_reason=response.finish_reason,
        )
        logger.info(
            "Gemini request completed request_id=%s provider_request_id=%s "
            "finish_reason=%s latency_ms=%.2f",
            request.request_id,
            response.provider_request_id,
            response.finish_reason,
            latency_ms,
        )
        return response

    async def aclose(self) -> None:
        """Release SDK transports when this provider created the client."""

        if self._owns_client:
            await self._client.aio.aclose()
            self._client.close()

    def _generation_config(self, request: ProviderBatchRequest) -> dict[str, Any]:
        return {
            "system_instruction": request.prompt.system_message,
            "temperature": request.generation.temperature,
            "top_p": request.generation.top_p,
            "max_output_tokens": request.generation.max_output_tokens,
            "response_mime_type": "application/json",
            "response_json_schema": dict(request.response_schema),
            "safety_settings": [item.as_sdk_dict() for item in self._config.safety_settings],
        }

    def _record_failure(
        self,
        request: ProviderBatchRequest,
        started: float,
        error: Exception,
    ) -> None:
        latency_ms = _latency_ms(started)
        retryable = _is_retryable(error, self._config.retry_policy.status_codes)
        self._emit_diagnostic(
            request=request,
            status="failed",
            latency_ms=latency_ms,
            error_type=type(error).__name__,
            retryable=retryable,
        )
        logger.warning(
            "Gemini request failed request_id=%s error_type=%s retryable=%s latency_ms=%.2f",
            request.request_id,
            type(error).__name__,
            retryable,
            latency_ms,
        )

    def _emit_diagnostic(
        self,
        *,
        request: ProviderBatchRequest,
        status: str,
        latency_ms: float,
        provider_request_id: str | None = None,
        token_usage: ProviderTokenUsage = ProviderTokenUsage(),
        finish_reason: ProviderFinishReason = ProviderFinishReason.UNKNOWN,
        error_type: str | None = None,
        retryable: bool = False,
    ) -> None:
        if self._diagnostic_sink is None:
            return
        diagnostic = ProviderRequestDiagnostic(
            request_id=request.request_id,
            provider_id=self.metadata.provider_id,
            model_id=self.metadata.model_id,
            status=status,
            latency_ms=latency_ms,
            provider_request_id=provider_request_id,
            token_usage=token_usage,
            finish_reason=finish_reason,
            error_type=error_type,
            retryable=retryable,
        )
        try:
            self._diagnostic_sink(diagnostic)
        except Exception:
            logger.exception(
                "Gemini diagnostic sink failed request_id=%s",
                request.request_id,
            )


def _create_google_client(config: GeminiProviderConfig) -> _GeminiClient:
    try:
        from google import genai
    except ImportError as error:
        raise SemanticConfigurationError(
            "GeminiProvider requires the official 'google-genai' package."
        ) from error

    client = genai.Client(
        api_key=config.api_key.get_secret_value(),
        http_options={
            "timeout": config.timeout_seconds * 1000,
            "retry_options": config.retry_policy.as_sdk_dict(),
        },
    )
    return cast(_GeminiClient, client)


def _adapt_response(response: Any, request: ProviderBatchRequest) -> ProviderBatchResponse:
    finish_reason = _extract_finish_reason(response)
    response_text = _response_text(response)
    if not response_text:
        if finish_reason is ProviderFinishReason.SAFETY:
            outputs = tuple(_refused_output(moment.candidate_id) for moment in request.batch.moments)
        else:
            raise ProviderExecutionError("Gemini returned an empty structured response.")
    else:
        outputs = _parse_outputs(response_text)

    return ProviderBatchResponse(
        outputs=outputs,
        provider_request_id=_optional_text(getattr(response, "response_id", None)),
        token_usage=_extract_token_usage(response),
        finish_reason=finish_reason,
        raw_response_hash=(
            hashlib.sha256(response_text.encode("utf-8")).hexdigest()
            if response_text
            else None
        ),
    )


def _parse_outputs(response_text: str) -> tuple[ProviderMomentOutput, ...]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ProviderExecutionError("Gemini returned invalid JSON.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("moments"), list):
        raise ProviderExecutionError("Gemini structured response is missing the moments array.")

    outputs: list[ProviderMomentOutput] = []
    for item in payload["moments"]:
        if not isinstance(item, dict):
            raise ProviderExecutionError("Gemini returned a non-object moment output.")
        category_value = item.get("category")
        viral_value = item.get("viral_potential")
        outputs.append(
            ProviderMomentOutput(
                candidate_id=_required_text(item, "candidate_id"),
                title=_optional_text(item.get("title")),
                description=_optional_text(item.get("description")),
                hashtags=_string_tuple(item.get("hashtags"), "hashtags"),
                explanation=_optional_text(item.get("explanation")),
                category=_category(category_value),
                viral_potential=_viral_potential(viral_value),
                refused=bool(item.get("refused", False)),
            )
        )
    return tuple(outputs)


def _category(value: Any) -> CategoryPrediction | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProviderExecutionError("Gemini category output must be an object.")
    return CategoryPrediction(
        category_id=_required_text(value, "category_id"),
        label=_required_text(value, "label"),
        confidence=_required_number(value, "confidence"),
    )


def _viral_potential(value: Any) -> ViralPotential | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProviderExecutionError("Gemini viral potential output must be an object.")
    return ViralPotential(
        score=_required_number(value, "score"),
        confidence=_required_number(value, "confidence"),
        rationale=_required_text(value, "rationale"),
        limitations=_required_text(value, "limitations"),
    )


def _required_text(value: Mapping[str, Any], key: str) -> str:
    result = _optional_text(value.get(key))
    if result is None:
        raise ProviderExecutionError(f"Gemini structured response is missing {key}.")
    return result


def _required_number(value: Mapping[str, Any], key: str) -> float:
    result = value.get(key)
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        raise ProviderExecutionError(f"Gemini structured response has an invalid {key}.")
    return float(result)


def _string_tuple(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProviderExecutionError(f"Gemini structured response has an invalid {key}.")
    return tuple(value)


def _refused_output(candidate_id: str) -> ProviderMomentOutput:
    return ProviderMomentOutput(
        candidate_id=candidate_id,
        title=None,
        description=None,
        hashtags=(),
        explanation=None,
        category=None,
        viral_potential=None,
        refused=True,
    )


def _response_text(response: Any) -> str:
    try:
        value = getattr(response, "text", None)
    except (AttributeError, ValueError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def _extract_token_usage(response: Any) -> ProviderTokenUsage:
    usage = getattr(response, "usage_metadata", None)
    return ProviderTokenUsage(
        input_tokens=_non_negative_int(getattr(usage, "prompt_token_count", 0)),
        output_tokens=_non_negative_int(getattr(usage, "candidates_token_count", 0)),
    )


def _extract_finish_reason(response: Any) -> ProviderFinishReason:
    candidates = getattr(response, "candidates", None) or ()
    raw_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    name = getattr(raw_reason, "name", None) or getattr(raw_reason, "value", None) or raw_reason
    normalized = str(name or "").upper().rsplit(".", maxsplit=1)[-1]
    if normalized == "STOP":
        return ProviderFinishReason.STOP
    if normalized in {"MAX_TOKENS", "LENGTH"}:
        return ProviderFinishReason.LENGTH
    if normalized in _SAFETY_FINISH_REASONS:
        return ProviderFinishReason.SAFETY
    if normalized in {"MALFORMED_FUNCTION_CALL", "OTHER", "UNEXPECTED_TOOL_CALL"}:
        return ProviderFinishReason.ERROR
    return ProviderFinishReason.UNKNOWN


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _non_negative_int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def _is_retryable(error: Exception, retry_status_codes: tuple[int, ...]) -> bool:
    status_code = getattr(error, "code", None) or getattr(error, "status_code", None)
    return status_code in retry_status_codes


def _latency_ms(started: float) -> float:
    return (monotonic() - started) * 1000

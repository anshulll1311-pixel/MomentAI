from backend.app.semantic.errors import SemanticBatchError
from backend.app.semantic.models import (
    ProviderMetadata,
    SemanticBatch,
    SemanticContext,
    SemanticMomentContext,
)


class SemanticBatchPlanner:
    """Group multiple moments under provider count and token limits."""

    def __init__(self, max_batch_size: int = 10, reserved_output_tokens: int = 2048) -> None:
        if max_batch_size <= 0 or reserved_output_tokens <= 0:
            raise ValueError("semantic batch limits must be positive")
        self._max_batch_size = max_batch_size
        self._reserved_output_tokens = reserved_output_tokens

    def plan(
        self,
        context: SemanticContext,
        provider: ProviderMetadata,
        moments: tuple[SemanticMomentContext, ...] | None = None,
    ) -> tuple[SemanticBatch, ...]:
        pending = moments if moments is not None else context.moments
        if not pending:
            return ()
        batch_limit = min(self._max_batch_size, provider.max_batch_size)
        token_limit = provider.max_input_tokens - self._reserved_output_tokens
        if token_limit <= 0:
            raise SemanticBatchError("Provider input limit leaves no room for semantic context.")

        batches: list[SemanticBatch] = []
        current: list[SemanticMomentContext] = []
        current_tokens = _base_context_tokens(context)
        for moment in pending:
            moment_tokens = _estimate_moment_tokens(moment)
            if moment_tokens + _base_context_tokens(context) > token_limit:
                raise SemanticBatchError(
                    f"Moment exceeds provider input limit: {moment.candidate_id}."
                )
            if current and (
                len(current) >= batch_limit or current_tokens + moment_tokens > token_limit
            ):
                batches.append(
                    SemanticBatch(
                        batch_id=f"batch-{len(batches) + 1:03d}",
                        moments=tuple(current),
                        estimated_input_tokens=current_tokens,
                    )
                )
                current = []
                current_tokens = _base_context_tokens(context)
            current.append(moment)
            current_tokens += moment_tokens

        if current:
            batches.append(
                SemanticBatch(
                    batch_id=f"batch-{len(batches) + 1:03d}",
                    moments=tuple(current),
                    estimated_input_tokens=current_tokens,
                )
            )
        return tuple(batches)


def _base_context_tokens(context: SemanticContext) -> int:
    return max(64, (len(context.locale) + len(context.tone) + len(context.profile_id)) // 4 + 64)


def _estimate_moment_tokens(moment: SemanticMomentContext) -> int:
    characters = len(moment.candidate_id) + len(moment.transcript_excerpt or "")
    characters += sum(len(item.signal_name) + len(item.analyzer_id) for item in moment.contributions)
    characters += sum(len(item.summary) for item in moment.deterministic_insights)
    return max(64, characters // 4 + 64)

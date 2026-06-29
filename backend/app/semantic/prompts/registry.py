from collections.abc import Iterable

from backend.app.semantic.errors import PromptNotFoundError, SemanticConfigurationError
from backend.app.semantic.models import PromptTemplate


class PromptRegistry:
    """Immutable registry keyed by explicit prompt ID and version."""

    def __init__(self, prompts: Iterable[PromptTemplate] = ()) -> None:
        ordered = tuple(prompts)
        keys = [(prompt.prompt_id, prompt.version) for prompt in ordered]
        if len(keys) != len(set(keys)):
            raise SemanticConfigurationError("semantic prompt ID and version pairs must be unique")
        self._ordered = ordered
        self._prompts = {
            (prompt.prompt_id, prompt.version): prompt for prompt in ordered
        }

    def get(self, prompt_id: str, version: str) -> PromptTemplate:
        try:
            return self._prompts[(prompt_id, version)]
        except KeyError as error:
            raise PromptNotFoundError(
                f"Semantic prompt is not registered: {prompt_id}@{version}."
            ) from error

    def list(self) -> tuple[PromptTemplate, ...]:
        return self._ordered

    def __len__(self) -> int:
        return len(self._ordered)

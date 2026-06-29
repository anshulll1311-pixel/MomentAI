from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    default_timeout_seconds: float = 10.0
    analyzer_timeouts: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_timeout_seconds <= 0:
            raise ValueError("default analyzer timeout must be positive")
        if any(timeout <= 0 for timeout in self.analyzer_timeouts.values()):
            raise ValueError("analyzer timeouts must be positive")
        object.__setattr__(
            self,
            "analyzer_timeouts",
            MappingProxyType(dict(self.analyzer_timeouts)),
        )

    def timeout_for(self, analyzer_id: str) -> float:
        return self.analyzer_timeouts.get(analyzer_id, self.default_timeout_seconds)

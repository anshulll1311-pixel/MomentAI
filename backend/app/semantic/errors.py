class SemanticError(RuntimeError):
    """Base error for semantic enrichment failures."""


class SemanticConfigurationError(SemanticError, ValueError):
    """Raised when semantic components are configured inconsistently."""


class SemanticValidationError(SemanticError, ValueError):
    """Raised when semantic input or provider output is invalid."""


class ProviderNotFoundError(SemanticConfigurationError):
    """Raised when no requested semantic provider is registered."""


class ProviderExecutionError(SemanticError):
    """Base error for provider execution failures."""


class ProviderTimeoutError(ProviderExecutionError):
    """Raised when a semantic provider exceeds its timeout."""


class PromptNotFoundError(SemanticConfigurationError):
    """Raised when a requested prompt version is not registered."""


class PromptRenderError(SemanticConfigurationError):
    """Raised when an immutable prompt template cannot be rendered."""


class SemanticCacheError(SemanticError):
    """Raised by semantic cache adapters."""


class SemanticBatchError(SemanticError, ValueError):
    """Raised when semantic moments cannot fit a provider batch."""

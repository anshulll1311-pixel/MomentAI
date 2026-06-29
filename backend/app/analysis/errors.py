"""Analysis lifecycle errors shared by repository adapters and APIs."""


class AnalysisLifecycleError(RuntimeError):
    """Base error for reusable analysis lifecycle failures."""


class AnalysisNotFoundError(AnalysisLifecycleError):
    """Raised when an analysis ID does not exist."""


class AnalysisNotReadyError(AnalysisLifecycleError):
    """Raised when a consumer requests a result that is not ready."""


class AnalysisExpiredError(AnalysisLifecycleError):
    """Raised when an analysis has passed its retention lifecycle."""


class AnalysisConflictError(AnalysisLifecycleError):
    """Raised when an atomic repository transition cannot be applied."""


class AnalysisExecutionError(AnalysisLifecycleError):
    """Raised when the media pipeline fails before publishing a result."""

    def __init__(self, analysis_id: str, message: str) -> None:
        self.analysis_id = analysis_id
        super().__init__(message)


class ArtifactLifecycleError(AnalysisLifecycleError):
    """Raised when an artifact reference cannot be managed safely."""


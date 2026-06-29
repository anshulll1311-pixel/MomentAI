class ExportError(RuntimeError):
    """Base error for synchronous export failures."""


class ExportPlanningError(ExportError, ValueError):
    """Raised when ranked moments cannot produce a valid export plan."""


class ExportToolUnavailableError(ExportError):
    """Raised when FFmpeg or FFprobe cannot be started."""


class ExportTimeoutError(ExportError):
    """Raised when a media process exceeds its configured timeout."""


class FFmpegExecutionError(ExportError):
    """Raised when FFmpeg rejects a clip extraction command."""


class ClipValidationError(ExportError):
    """Raised when an extracted clip is missing, corrupt, or out of bounds."""


class ExportStorageError(ExportError):
    """Raised when local export artifacts cannot be stored."""


class InsufficientExportStorageError(ExportStorageError):
    """Raised when local storage has no remaining capacity."""


class ExportPackageError(ExportError):
    """Raised when the downloadable package cannot be built."""


class ExportArtifactNotFoundError(ExportError):
    """Raised when a requested export artifact does not exist."""

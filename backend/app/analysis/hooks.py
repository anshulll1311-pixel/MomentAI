"""Optional, failure-isolated AnalysisCoordinator lifecycle hooks."""

from typing import Protocol

from backend.app.analysis.models import AnalysisRecord


class AnalysisLifecycleHook(Protocol):
    async def analysis_started(self, record: AnalysisRecord) -> None: ...

    async def analysis_completed(self, record: AnalysisRecord) -> None: ...

    async def analysis_failed(self, record: AnalysisRecord) -> None: ...

    async def analysis_expired(self, record: AnalysisRecord) -> None: ...


class NoOpAnalysisLifecycleHook:
    """Default hook preserving lifecycle extension points without side effects."""

    async def analysis_started(self, record: AnalysisRecord) -> None:
        return None

    async def analysis_completed(self, record: AnalysisRecord) -> None:
        return None

    async def analysis_failed(self, record: AnalysisRecord) -> None:
        return None

    async def analysis_expired(self, record: AnalysisRecord) -> None:
        return None


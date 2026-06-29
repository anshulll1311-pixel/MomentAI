"""Consistent HTTP mapping for shared analysis lifecycle failures."""

import logging

from fastapi import HTTPException, status

from backend.app.analysis import (
    AnalysisExecutionError,
    AnalysisExpiredError,
    AnalysisNotFoundError,
)
from backend.app.services.scene_service import (
    SceneDetectionError,
    SceneThumbnailError,
    SceneTimeoutError,
    SceneToolUnavailableError,
)
from backend.app.services.video_service import (
    InvalidVideoError,
    VideoProbeTimeoutError,
    VideoToolUnavailableError,
)

logger = logging.getLogger(__name__)


def analysis_state_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, AnalysisNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, AnalysisExpiredError):
        return HTTPException(status_code=status.HTTP_410_GONE, detail=str(error))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def pipeline_http_exception(error: AnalysisExecutionError) -> HTTPException:
    cause = error.__cause__
    if isinstance(cause, KeyError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(cause))
    if isinstance(cause, (InvalidVideoError, SceneDetectionError, SceneThumbnailError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(cause))
    if isinstance(cause, (VideoProbeTimeoutError, SceneTimeoutError, TimeoutError)):
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(cause))
    if isinstance(cause, (VideoToolUnavailableError, SceneToolUnavailableError)):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(cause))
    logger.error(
        "Analysis pipeline failed analysis_id=%s error_type=%s",
        error.analysis_id,
        type(cause).__name__ if cause is not None else "unknown",
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Analysis processing failed. analysis_id={error.analysis_id}",
    )

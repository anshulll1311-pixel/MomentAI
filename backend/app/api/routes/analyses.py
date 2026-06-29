import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.app.analysis import (
    AnalysisExecutionError,
    AnalysisExpiredError,
    AnalysisNotFoundError,
    AnalysisNotReadyError,
    ArtifactKind,
)
from backend.app.api.dependencies import (
    build_export_engine,
    get_analysis_coordinator,
    get_semantic_service,
)
from backend.app.api.analysis_errors import (
    analysis_state_http_exception,
    pipeline_http_exception,
)
from backend.app.api.presenters import (
    analysis_record_response,
    export_response,
    moments_response,
    semantic_response,
)
from backend.app.core.config import get_settings
from backend.app.exporting import ExportOptions
from backend.app.exporting.errors import (
    ClipValidationError,
    ExportPackageError,
    ExportPlanningError,
    ExportStorageError,
    ExportTimeoutError,
    ExportToolUnavailableError,
    FFmpegExecutionError,
    InsufficientExportStorageError,
)
from backend.app.schemas.analyses import (
    AnalysisExportRequest,
    AnalysisRecordResponse,
    AnalysisSemanticResponse,
    SemanticGenerationRequest,
)
from backend.app.schemas.exports import ExportResponse
from backend.app.schemas.moments import MomentsResponse
from backend.app.semantic import SemanticOptions
from backend.app.semantic.errors import SemanticValidationError
from backend.app.services.storage import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFileTypeError,
    store_upload,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=AnalysisRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and create or reuse one immutable analysis",
)
async def create_analysis(
    file: UploadFile = File(...),
    profile: str = Query(default="default", min_length=1, max_length=64),
) -> AnalysisRecordResponse:
    settings = get_settings()
    try:
        stored = await store_upload(
            upload=file,
            destination=settings.upload_dir,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except EmptyFileError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except InvalidFileTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except FileTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    try:
        coordinated = await get_analysis_coordinator().create_or_reuse(
            source_path=stored.path,
            source_filename=stored.original_filename,
            profile_id=profile,
        )
    except AnalysisExecutionError as error:
        raise pipeline_http_exception(error) from error

    return analysis_record_response(
        coordinated.record,
        reused=coordinated.reused,
        api_prefix=settings.api_prefix,
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisRecordResponse,
    summary="Get analysis lifecycle status and summary",
)
async def get_analysis(analysis_id: str) -> AnalysisRecordResponse:
    settings = get_settings()
    try:
        record = await get_analysis_coordinator().get_record(analysis_id)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return analysis_record_response(
        record,
        reused=None,
        api_prefix=settings.api_prefix,
    )


@router.get(
    "/{analysis_id}/moments",
    response_model=MomentsResponse,
    summary="Read ranked moments from an existing analysis",
)
async def get_analysis_moments(analysis_id: str) -> MomentsResponse:
    settings = get_settings()
    coordinator = get_analysis_coordinator()
    try:
        record = await coordinator.get_record(analysis_id)
        result = await coordinator.get_result(analysis_id)
    except (AnalysisNotFoundError, AnalysisExpiredError, AnalysisNotReadyError) as error:
        raise analysis_state_http_exception(error) from error
    return moments_response(
        result,
        source_filename=record.source_filename,
        thumbnail_directory=settings.thumbnail_dir,
    )


@router.post(
    "/{analysis_id}/semantic",
    response_model=AnalysisSemanticResponse,
    summary="Generate semantic metadata from an existing analysis",
)
async def generate_analysis_semantics(
    analysis_id: str,
    request: SemanticGenerationRequest,
) -> AnalysisSemanticResponse:
    coordinator = get_analysis_coordinator()
    try:
        result = await coordinator.get_result(analysis_id)
        options = SemanticOptions(
            provider_id=request.provider_id,
            locale=request.locale,
            tone=request.tone,
            selected_ranks=tuple(request.selected_ranks),
        )
        semantic_result = await get_semantic_service().enrich(result, options)
    except (AnalysisNotFoundError, AnalysisExpiredError, AnalysisNotReadyError) as error:
        raise analysis_state_http_exception(error) from error
    except (SemanticValidationError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return semantic_response(analysis_id, semantic_result)


@router.post(
    "/{analysis_id}/export",
    response_model=ExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Export clips from an existing immutable analysis",
)
async def export_analysis(
    analysis_id: str,
    request: AnalysisExportRequest,
) -> ExportResponse:
    settings = get_settings()
    coordinator = get_analysis_coordinator()
    try:
        record = await coordinator.get_record(analysis_id)
        result = await coordinator.get_result(analysis_id)
        export_result = await build_export_engine(settings).export(
            analysis=result,
            source_filename=record.source_filename,
            options=ExportOptions(
                profile_id=record.profile_id,
                preset=request.preset,
                top_k=request.top_k,
                selected_ranks=tuple(request.selected_ranks),
                padding_before_seconds=request.padding_before_seconds,
                padding_after_seconds=request.padding_after_seconds,
            ),
        )
        references = tuple(
            coordinator.artifact_reference(ArtifactKind.EXPORTED_CLIP, artifact.path)
            for artifact in export_result.artifacts
        )
        await coordinator.add_artifacts(analysis_id, references)
    except (AnalysisNotFoundError, AnalysisExpiredError, AnalysisNotReadyError) as error:
        raise analysis_state_http_exception(error) from error
    except (ExportPlanningError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ExportTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except ExportToolUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except InsufficientExportStorageError as error:
        raise HTTPException(status_code=507, detail=str(error)) from error
    except (
        FFmpegExecutionError,
        ClipValidationError,
        ExportPackageError,
        ExportStorageError,
    ) as error:
        logger.exception("Analysis export failed analysis_id=%s", analysis_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video export failed.",
        ) from error
    return export_response(export_result, api_prefix=settings.api_prefix)


@router.delete(
    "/{analysis_id}",
    response_model=AnalysisRecordResponse,
    summary="Expire an analysis and retire managed artifacts",
)
async def expire_analysis(analysis_id: str) -> AnalysisRecordResponse:
    settings = get_settings()
    try:
        record = await get_analysis_coordinator().expire(analysis_id)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return analysis_record_response(
        record,
        reused=None,
        api_prefix=settings.api_prefix,
    )

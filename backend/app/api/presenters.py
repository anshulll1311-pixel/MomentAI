"""Pure API projections for immutable analysis and derived results."""

from pathlib import Path

from backend.app.analysis import AnalysisRecord
from backend.app.exporting import ExportResult
from backend.app.schemas.analyses import (
    AnalysisRecordResponse,
    AnalysisSemanticResponse,
    AnalysisSummaryResponse,
    SemanticDiagnosticResponse,
    SemanticMomentResponse,
)
from backend.app.schemas.exports import (
    ExportClipResponse,
    ExportDiagnosticResponse,
    ExportResponse,
)
from backend.app.schemas.moments import (
    AnalyzerExecutionResponse,
    MomentInsightResponse,
    MomentsResponse,
    PipelineDiagnosticResponse,
    RankedMomentResponse,
    SignalContributionResponse,
)
from backend.app.semantic.models import SemanticResult
from backend.app.services.moment_pipeline_service import AnalysisResult


def analysis_record_response(
    record: AnalysisRecord,
    *,
    reused: bool | None,
    api_prefix: str,
) -> AnalysisRecordResponse:
    result = record.result
    summary = None
    if result is not None:
        summary = AnalysisSummaryResponse(
            duration=round(result.video_metadata.duration_seconds, 3),
            width=result.video_metadata.width,
            height=result.video_metadata.height,
            scene_count=len(result.scene_result.scenes),
            transcript_language=(
                result.transcript_result.language
                if result.transcript_result is not None
                else None
            ),
            transcript_segment_count=(
                len(result.transcript_result.segments)
                if result.transcript_result is not None
                else 0
            ),
            moment_count=len(result.engine_result.moments),
        )
    base = f"{api_prefix}/analyses/{record.analysis_id}"
    return AnalysisRecordResponse(
        success=True,
        analysis_id=record.analysis_id,
        status=record.status,
        reused=reused,
        filename=record.source_filename,
        profile=record.profile_id,
        source_fingerprint=record.source_fingerprint,
        created_at=record.created_at,
        completed_at=record.completed_at,
        summary=summary,
        failure=record.failure.message if record.failure is not None else None,
        moments_url=f"{base}/moments",
        semantic_url=f"{base}/semantic",
        export_url=f"{base}/export",
    )


def moments_response(
    result: AnalysisResult,
    *,
    source_filename: str,
    thumbnail_directory: Path,
) -> MomentsResponse:
    thumbnails_by_scene = {
        scene.id: f"/thumbnails/{scene.thumbnail_path.relative_to(thumbnail_directory).as_posix()}"
        for scene in result.scene_result.scenes
    }
    return MomentsResponse(
        success=True,
        profile=result.engine_result.profile_id,
        filename=source_filename,
        duration=round(result.video_metadata.duration_seconds, 3),
        scene_count=len(result.scene_result.scenes),
        transcript_language=(
            result.transcript_result.language if result.transcript_result is not None else None
        ),
        transcript_segment_count=(
            len(result.transcript_result.segments) if result.transcript_result is not None else 0
        ),
        moments=[
            RankedMomentResponse(
                rank=rank,
                candidate_id=moment.candidate.candidate_id,
                start=round(moment.candidate.start_seconds, 3),
                end=round(moment.candidate.end_seconds, 3),
                duration=round(moment.candidate.duration_seconds, 3),
                scene_ids=list(moment.candidate.scene_ids),
                score=round(moment.score, 6),
                confidence=round(moment.confidence, 6),
                thumbnails=[
                    thumbnails_by_scene[scene_id]
                    for scene_id in moment.candidate.scene_ids
                    if scene_id in thumbnails_by_scene
                ],
                contributions=[
                    SignalContributionResponse(
                        analyzer_id=item.analyzer_id,
                        signal_name=item.signal_name,
                        raw_score=round(item.raw_score, 6),
                        confidence=round(item.confidence, 6),
                        weight=item.weight,
                        weighted_value=round(item.weighted_value, 6),
                    )
                    for item in moment.contributions
                ],
                insights=[
                    MomentInsightResponse(
                        insight_type=item.insight_type,
                        summary=item.summary,
                        evidence=dict(item.evidence),
                    )
                    for item in moment.insights
                ],
            )
            for rank, moment in enumerate(result.engine_result.moments, start=1)
        ],
        analyzers=[
            AnalyzerExecutionResponse(
                analyzer_id=item.analyzer_id,
                version=item.version,
                status=str(item.status),
                duration_ms=round(item.duration_ms, 3),
                cache_key=item.cache_key,
                error=item.error,
            )
            for item in result.engine_result.executions
        ],
        diagnostics=[
            PipelineDiagnosticResponse(
                stage=item.stage,
                status=item.status,
                message=item.message,
            )
            for item in result.diagnostics
        ],
    )


def semantic_response(
    analysis_id: str,
    result: SemanticResult,
) -> AnalysisSemanticResponse:
    return AnalysisSemanticResponse(
        success=True,
        analysis_id=analysis_id,
        status=str(result.status),
        provider_id=result.provider_id,
        model_id=result.model_id,
        batch_count=result.batch_count,
        cache_hits=result.cache_hits,
        moments=[
            SemanticMomentResponse(
                candidate_id=moment.candidate_id,
                rank=moment.rank,
                status=str(moment.status),
                content_origin=str(moment.content_origin),
                title=moment.title,
                description=moment.description,
                hashtags=list(moment.hashtags),
                explanation=moment.explanation,
            )
            for moment in result.moments
        ],
        diagnostics=[
            SemanticDiagnosticResponse(
                stage=item.stage,
                status=item.status,
                message=item.message,
                candidate_id=item.candidate_id,
                provider_id=item.provider_id,
                retryable=item.retryable,
            )
            for item in result.diagnostics
        ],
    )


def export_response(result: ExportResult, *, api_prefix: str) -> ExportResponse:
    return ExportResponse(
        success=True,
        export_id=result.export_id,
        profile=result.profile_id,
        preset=result.preset,
        clip_count=len(result.artifacts),
        clips=[
            ExportClipResponse(
                clip_id=artifact.spec.clip_id,
                rank=artifact.spec.rank,
                start=round(artifact.spec.start_seconds, 3),
                end=round(artifact.spec.end_seconds, 3),
                duration=round(artifact.metadata.duration_seconds, 3),
                score=round(artifact.spec.score, 6),
                size_bytes=artifact.metadata.size_bytes,
                sha256=artifact.sha256,
                download_url=(
                    f"{api_prefix}/exports/{result.export_id}/clips/{artifact.spec.clip_id}"
                ),
            )
            for artifact in result.artifacts
        ],
        manifest_url=f"{api_prefix}/exports/{result.export_id}/manifest",
        package_url=f"{api_prefix}/exports/{result.export_id}/package",
        package_sha256=result.package_sha256,
        diagnostics=[
            ExportDiagnosticResponse(
                stage=item.stage,
                status=item.status,
                message=item.message,
            )
            for item in result.manifest.diagnostics
        ],
    )

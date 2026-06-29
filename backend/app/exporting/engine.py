import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.app.core.version import (
    EXPORT_MANIFEST_VERSION,
    MIE_VERSION,
    MOMENTAI_VERSION,
    PIPELINE_VERSION,
)
from backend.app.exporting.ffmpeg.clip_extractor import ClipExtractor
from backend.app.exporting.models import (
    EXPORT_PRESETS,
    ClipArtifact,
    ExportManifest,
    ExportOptions,
    ExportResult,
    ManifestClip,
    ManifestContribution,
    ManifestDiagnostic,
    ManifestExportOptions,
    ManifestInsight,
    ManifestVideo,
)
from backend.app.exporting.packaging.zip_package_builder import PackageBuilder
from backend.app.exporting.planner import ExportPlanner
from backend.app.exporting.storage.local_artifact_storage import LocalArtifactStorage
from backend.app.services.moment_pipeline_service import AnalysisResult

logger = logging.getLogger(__name__)


class ExportEngine:
    """Synchronously turn one precomputed analysis into downloadable artifacts."""

    def __init__(
        self,
        planner: ExportPlanner,
        clip_extractor: ClipExtractor,
        package_builder: PackageBuilder,
        artifact_storage: LocalArtifactStorage,
    ) -> None:
        self._planner = planner
        self._clip_extractor = clip_extractor
        self._package_builder = package_builder
        self._artifact_storage = artifact_storage

    async def export(
        self,
        analysis: AnalysisResult,
        source_filename: str,
        options: ExportOptions,
    ) -> ExportResult:
        if analysis.engine_result.profile_id != options.profile_id:
            raise ValueError("Export profile does not match the supplied analysis result.")
        if not analysis.source_path.is_file():
            raise ValueError("The analyzed source video is no longer available.")

        specs = self._planner.plan(analysis, options)
        preset = EXPORT_PRESETS[options.preset]
        export_id = f"exp_{uuid4().hex}"
        logger.info("Starting synchronous export %s with %s clips", export_id, len(specs))
        self._artifact_storage.prepare(export_id)

        try:
            artifacts = []
            for spec in specs:
                temporary_path = self._artifact_storage.temporary_clip_path(
                    export_id,
                    spec.clip_id,
                )
                extracted = await self._clip_extractor.extract(
                    source_path=analysis.source_path,
                    spec=spec,
                    preset=preset,
                    output_path=temporary_path,
                )
                artifacts.append(self._artifact_storage.publish_clip(export_id, extracted))
            published_artifacts = tuple(artifacts)
            manifest = _build_manifest(
                export_id=export_id,
                source_filename=Path(source_filename).name,
                analysis=analysis,
                options=options,
                artifacts=published_artifacts,
            )
            manifest_path = self._artifact_storage.write_manifest(export_id, manifest)
            checksums_path = self._artifact_storage.write_checksums(
                export_id,
                published_artifacts,
            )
            temporary_package = self._artifact_storage.temporary_package_path(export_id)
            await self._package_builder.build(
                output_path=temporary_package,
                manifest_path=manifest_path,
                checksums_path=checksums_path,
                artifacts=published_artifacts,
            )
            package_path = self._artifact_storage.publish_package(export_id, temporary_package)
            package_sha256 = await asyncio.to_thread(_sha256_file, package_path)
        except BaseException:
            self._artifact_storage.cleanup_failed_export(export_id)
            logger.exception("Synchronous export %s failed", export_id)
            raise

        self._artifact_storage.cleanup_temporary(export_id)
        logger.info("Synchronous export %s completed", export_id)
        return ExportResult(
            export_id=export_id,
            profile_id=analysis.engine_result.profile_id,
            preset=options.preset,
            artifacts=published_artifacts,
            manifest=manifest,
            manifest_path=manifest_path,
            package_path=package_path,
            package_sha256=package_sha256,
        )


def _build_manifest(
    export_id: str,
    source_filename: str,
    analysis: AnalysisResult,
    options: ExportOptions,
    artifacts: tuple[ClipArtifact, ...],
) -> ExportManifest:
    metadata = analysis.video_metadata
    return ExportManifest(
        manifest_version=EXPORT_MANIFEST_VERSION,
        momentai_version=MOMENTAI_VERSION,
        pipeline_version=PIPELINE_VERSION,
        mie_version=MIE_VERSION,
        export_id=export_id,
        created_at=datetime.now(UTC),
        source_filename=source_filename,
        source_fingerprint=analysis.source_fingerprint,
        profile=analysis.engine_result.profile_id,
        preset=options.preset,
        options=ManifestExportOptions(
            top_k=options.top_k,
            selected_ranks=list(options.selected_ranks),
            padding_before_seconds=options.padding_before_seconds,
            padding_after_seconds=options.padding_after_seconds,
        ),
        video=ManifestVideo(
            duration_seconds=metadata.duration_seconds,
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
            bitrate=metadata.bitrate,
            rotation=metadata.rotation,
            file_size_bytes=metadata.file_size_bytes,
        ),
        diagnostics=[
            ManifestDiagnostic(
                stage=item.stage,
                status=item.status,
                message=item.message,
            )
            for item in analysis.diagnostics
        ],
        clips=[
            ManifestClip(
                clip_id=artifact.spec.clip_id,
                candidate_id=artifact.spec.candidate_id,
                rank=artifact.spec.rank,
                start_seconds=artifact.spec.start_seconds,
                end_seconds=artifact.spec.end_seconds,
                duration_seconds=artifact.metadata.duration_seconds,
                scene_ids=list(artifact.spec.scene_ids),
                score=artifact.spec.score,
                confidence=artifact.spec.confidence,
                contributions=[
                    ManifestContribution(
                        analyzer_id=item.analyzer_id,
                        signal_name=item.signal_name,
                        raw_score=item.raw_score,
                        confidence=item.confidence,
                        weight=item.weight,
                        weighted_value=item.weighted_value,
                    )
                    for item in artifact.spec.contributions
                ],
                insights=[
                    ManifestInsight(
                        insight_type=item.insight_type,
                        summary=item.summary,
                        evidence=dict(item.evidence),
                    )
                    for item in artifact.spec.insights
                ],
                filename=artifact.path.name,
                size_bytes=artifact.metadata.size_bytes,
                sha256=artifact.sha256,
                width=artifact.metadata.width,
                height=artifact.metadata.height,
                video_codec=artifact.metadata.video_codec,
                audio_codec=artifact.metadata.audio_codec,
            )
            for artifact in artifacts
        ],
        transforms=[],
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

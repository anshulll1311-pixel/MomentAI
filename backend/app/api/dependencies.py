"""Shared application composition for reusable analysis consumers."""

import hashlib
import json
from functools import lru_cache

from backend.app.analysis import (
    AnalysisCoordinator,
    InMemoryAnalysisRepository,
    LocalArtifactManager,
)
from backend.app.core.config import PROJECT_ROOT, Settings, get_settings
from backend.app.exporting import ExportEngine
from backend.app.exporting.ffmpeg import (
    FFmpegClipExtractor,
    FFmpegCommandBuilder,
    FFmpegProcessRunner,
    FFprobeOutputValidator,
)
from backend.app.exporting.packaging import ZipPackageBuilder
from backend.app.exporting.planner import ExportPlanner
from backend.app.exporting.storage import LocalArtifactStorage
from backend.app.intelligence import create_default_engine
from backend.app.semantic import (
    ProviderRegistry,
    SemanticIntelligenceService,
    create_semantic_intelligence_service,
)
from backend.app.semantic.providers import GeminiProvider, GeminiProviderConfig
from backend.app.services.moment_pipeline_service import MomentPipelineService
from backend.app.services.scene_service import SceneService
from backend.app.services.transcript_service import TranscriptService
from backend.app.services.video_service import VideoService


@lru_cache
def get_analysis_repository() -> InMemoryAnalysisRepository:
    return InMemoryAnalysisRepository()


@lru_cache
def get_moment_pipeline() -> MomentPipelineService:
    settings = get_settings()
    video_service = VideoService(
        ffprobe_binary=settings.ffprobe_binary,
        timeout_seconds=settings.ffprobe_timeout_seconds,
    )
    scene_service = SceneService(
        video_service=video_service,
        thumbnail_directory=settings.thumbnail_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        threshold=settings.scene_threshold,
        minimum_scene_duration_seconds=settings.minimum_scene_duration_seconds,
        detection_timeout_seconds=settings.scene_detection_timeout_seconds,
        thumbnail_timeout_seconds=settings.ffmpeg_timeout_seconds,
    )
    transcript_service = TranscriptService(
        video_service=video_service,
        scene_service=scene_service,
        temporary_directory=settings.transcript_temp_dir,
        model_directory=settings.whisper_model_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        beam_size=settings.whisper_beam_size,
        audio_timeout_seconds=settings.audio_extraction_timeout_seconds,
        transcription_timeout_seconds=settings.transcription_timeout_seconds,
    )
    return MomentPipelineService(
        video_service=video_service,
        scene_service=scene_service,
        transcript_service=transcript_service,
        engine=create_default_engine(),
    )


@lru_cache
def get_analysis_coordinator() -> AnalysisCoordinator:
    settings = get_settings()
    artifact_manager = LocalArtifactManager(
        (
            settings.upload_dir,
            settings.thumbnail_dir,
            settings.transcript_temp_dir,
            settings.export_dir,
            settings.export_temp_dir,
            PROJECT_ROOT / "clips",
            PROJECT_ROOT / "frames",
            PROJECT_ROOT / "temp",
        )
    )
    return AnalysisCoordinator(
        repository=get_analysis_repository(),
        artifact_manager=artifact_manager,
        pipeline=get_moment_pipeline(),
        configuration_version=_analysis_configuration_hash(settings),
    )


@lru_cache
def get_semantic_service() -> SemanticIntelligenceService:
    settings = get_settings()
    providers = ()
    if settings.gemini_api_key is not None and settings.gemini_model_id:
        providers = (
            GeminiProvider(
                GeminiProviderConfig(
                    api_key=settings.gemini_api_key,
                    model_id=settings.gemini_model_id,
                    model_version=settings.gemini_model_version,
                    timeout_seconds=settings.gemini_timeout_seconds,
                )
            ),
        )
    return create_semantic_intelligence_service(
        ProviderRegistry(providers),
        provider_timeout_seconds=settings.semantic_provider_timeout_seconds,
    )


def build_export_engine(settings: Settings | None = None) -> ExportEngine:
    resolved = settings or get_settings()
    return ExportEngine(
        planner=ExportPlanner(),
        clip_extractor=FFmpegClipExtractor(
            command_builder=FFmpegCommandBuilder(resolved.ffmpeg_binary),
            process_runner=FFmpegProcessRunner(resolved.export_ffmpeg_timeout_seconds),
            output_validator=FFprobeOutputValidator(
                resolved.ffprobe_binary,
                resolved.export_ffprobe_timeout_seconds,
            ),
        ),
        package_builder=ZipPackageBuilder(),
        artifact_storage=LocalArtifactStorage(
            resolved.export_dir,
            resolved.export_temp_dir,
        ),
    )


def reset_application_dependencies() -> None:
    """Clear process-local singletons for tests and application reloads."""

    get_analysis_coordinator.cache_clear()
    get_analysis_repository.cache_clear()
    get_moment_pipeline.cache_clear()
    get_semantic_service.cache_clear()


def _analysis_configuration_hash(settings: Settings) -> str:
    material = json.dumps(
        {
            "version": settings.analysis_configuration_version,
            "ffmpeg_binary": settings.ffmpeg_binary,
            "ffprobe_binary": settings.ffprobe_binary,
            "scene_threshold": settings.scene_threshold,
            "minimum_scene_duration_seconds": settings.minimum_scene_duration_seconds,
            "whisper_model_size": settings.whisper_model_size,
            "whisper_device": settings.whisper_device,
            "whisper_compute_type": settings.whisper_compute_type,
            "whisper_beam_size": settings.whisper_beam_size,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

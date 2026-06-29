import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.app.intelligence import (
    EngineResult,
    MomentIntelligenceEngine,
    PrecomputedAnalysisInputs,
    PrecomputedContextBuilder,
)
from backend.app.services.scene_service import SceneDetectionResult, SceneService, SceneServiceError
from backend.app.services.transcript_service import TranscriptResult, TranscriptService, TranscriptServiceError
from backend.app.services.video_service import VideoMetadata, VideoService, VideoServiceError

logger = logging.getLogger(__name__)
FINGERPRINT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class PipelineDiagnostic:
    stage: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class MomentPipelineResult:
    video_metadata: VideoMetadata
    scene_result: SceneDetectionResult
    transcript_result: TranscriptResult | None
    engine_result: EngineResult
    diagnostics: tuple[PipelineDiagnostic, ...]


class MomentPipelineService:
    """Connect real media services to the deterministic Moment Intelligence Engine."""

    def __init__(
        self,
        video_service: VideoService,
        scene_service: SceneService,
        transcript_service: TranscriptService,
        engine: MomentIntelligenceEngine,
        context_builder: PrecomputedContextBuilder | None = None,
    ) -> None:
        self._video_service = video_service
        self._scene_service = scene_service
        self._transcript_service = transcript_service
        self._engine = engine
        self._context_builder = context_builder or PrecomputedContextBuilder()

    async def analyze(
        self,
        video_path: Path,
        profile_id: str = "default",
    ) -> MomentPipelineResult:
        logger.info("Starting Moment Intelligence pipeline for %s", video_path.name)
        metadata = await self._video_service.extract_metadata(video_path)
        scene_result = await self._scene_service.detect_scenes(video_path)

        diagnostics = []
        transcript_result = None
        try:
            transcript_result = await self._transcript_service.transcribe(video_path)
        except (TranscriptServiceError, SceneServiceError, VideoServiceError) as error:
            logger.warning("Transcript stage degraded for %s: %s", video_path.name, error)
            diagnostics.append(
                PipelineDiagnostic(
                    stage="transcript",
                    status="degraded",
                    message=str(error),
                )
            )

        source_fingerprint = await asyncio.to_thread(_sha256_file, video_path)
        context = self._context_builder.build(
            PrecomputedAnalysisInputs(
                source_fingerprint=source_fingerprint,
                video_path=video_path,
                video_metadata=metadata,
                scenes=scene_result.scenes,
                transcript_segments=(
                    transcript_result.segments if transcript_result is not None else ()
                ),
                resources={
                    "transcript_language": (
                        transcript_result.language if transcript_result is not None else None
                    )
                },
            )
        )
        engine_result = await self._engine.analyze(context, profile_id=profile_id)
        logger.info(
            "Moment Intelligence pipeline ranked %s moments for %s",
            len(engine_result.moments),
            video_path.name,
        )
        return MomentPipelineResult(
            video_metadata=metadata,
            scene_result=scene_result,
            transcript_result=transcript_result,
            engine_result=engine_result,
            diagnostics=tuple(diagnostics),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(FINGERPRINT_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()

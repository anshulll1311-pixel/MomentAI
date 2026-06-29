import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from zipfile import ZipFile

from backend.app.core.version import (
    EXPORT_MANIFEST_VERSION,
    MIE_VERSION,
    MOMENTAI_VERSION,
    PIPELINE_VERSION,
)
from backend.app.exporting.engine import ExportEngine
from backend.app.exporting.errors import ExportArtifactNotFoundError, ExportPlanningError
from backend.app.exporting.ffmpeg.clip_extractor import ClipExtractor
from backend.app.exporting.ffmpeg.command_builder import FFmpegCommandBuilder
from backend.app.exporting.models import (
    EXPORT_PRESETS,
    ClipArtifact,
    ClipMediaMetadata,
    ClipSpec,
    ExportOptions,
    ExportPresetName,
)
from backend.app.exporting.packaging import ZipPackageBuilder
from backend.app.exporting.planner import ExportPlanner
from backend.app.exporting.storage import LocalArtifactStorage
from backend.app.intelligence import AnalysisContext, create_default_engine
from backend.app.services.moment_pipeline_service import AnalysisResult, PipelineDiagnostic
from backend.app.services.scene_service import Scene, SceneDetectionResult
from backend.app.services.transcript_service import TranscriptResult, TranscriptSegment
from backend.app.services.video_service import VideoMetadata


class FakeClipExtractor(ClipExtractor):
    def __init__(self) -> None:
        self.calls: list[tuple[ClipSpec, ExportPresetName]] = []

    async def extract(self, source_path, spec, preset, output_path):  # type: ignore[no-untyped-def]
        self.calls.append((spec, preset.name))
        payload = f"clip:{source_path.name}:{spec.clip_id}".encode()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        return ClipArtifact(
            spec=spec,
            path=output_path,
            metadata=ClipMediaMetadata(
                duration_seconds=spec.duration_seconds,
                width=1280,
                height=720,
                video_codec="h264",
                audio_codec="aac",
                size_bytes=len(payload),
            ),
            sha256=hashlib.sha256(payload).hexdigest(),
        )


async def make_analysis(video_path: Path) -> AnalysisResult:
    metadata = VideoMetadata(
        duration_seconds=12.0,
        width=1280,
        height=720,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        bitrate=2_000_000,
        rotation=None,
        file_size_bytes=video_path.stat().st_size,
    )
    scenes = (
        Scene(1, 0.0, 5.0, 5.0, video_path.parent / "scene-001.jpg"),
        Scene(2, 5.0, 12.0, 7.0, video_path.parent / "scene-002.jpg"),
    )
    segments = (
        TranscriptSegment(0.0, 4.0, "first scene words", 1),
        TranscriptSegment(6.0, 10.0, "second scene words", 2),
    )
    fingerprint = hashlib.sha256(video_path.read_bytes()).hexdigest()
    context = AnalysisContext(
        source_fingerprint=fingerprint,
        video_path=video_path,
        video_metadata=metadata,
        scenes=scenes,
        transcript_segments=segments,
    )
    engine_result = await create_default_engine().analyze(context)
    return AnalysisResult(
        source_path=video_path,
        source_fingerprint=fingerprint,
        video_metadata=metadata,
        scene_result=SceneDetectionResult(duration_seconds=12.0, scenes=scenes),
        transcript_result=TranscriptResult(
            language="en",
            duration_seconds=12.0,
            segments=segments,
        ),
        engine_result=engine_result,
        diagnostics=(PipelineDiagnostic("transcript", "ok", "Transcript available."),),
    )


class ExportEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_is_immutable_and_planner_clamps_padding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"source-video")
            analysis = await make_analysis(video)

            with self.assertRaises(FrozenInstanceError):
                analysis.source_fingerprint = "changed"  # type: ignore[misc]

            specs = ExportPlanner().plan(
                analysis,
                ExportOptions(
                    selected_ranks=(1, 2),
                    padding_before_seconds=10,
                    padding_after_seconds=10,
                ),
            )

        self.assertEqual(specs[0].start_seconds, 0.0)
        self.assertEqual(specs[-1].end_seconds, 12.0)
        self.assertEqual([item.rank for item in specs], [1, 2])

    async def test_planner_rejects_unknown_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "source.mp4"
            video.write_bytes(b"source-video")
            analysis = await make_analysis(video)
            with self.assertRaises(ExportPlanningError):
                ExportPlanner().plan(analysis, ExportOptions(selected_ranks=(3,)))

    def test_presets_only_change_ffmpeg_output_configuration(self) -> None:
        spec = ClipSpec(
            clip_id="moment-001",
            candidate_id="scene-1",
            rank=1,
            start_seconds=1.0,
            end_seconds=4.0,
            scene_ids=(1,),
            score=0.8,
            confidence=1.0,
            contributions=(),
            insights=(),
        )
        builder = FFmpegCommandBuilder("ffmpeg")
        source = Path("source.mp4")
        output = Path("output.part.mp4")

        standard = builder.build(source, output, spec, EXPORT_PRESETS[ExportPresetName.STANDARD])
        preview = builder.build(source, output, spec, EXPORT_PRESETS[ExportPresetName.PREVIEW])
        shorts = builder.build(
            source,
            output,
            spec,
            EXPORT_PRESETS[ExportPresetName.YOUTUBE_SHORTS],
        )

        self.assertNotIn("-vf", standard)
        self.assertIn("-vf", preview)
        self.assertIn("scale=854:480", preview[preview.index("-vf") + 1])
        self.assertIn("pad=1080:1920", shorts[shorts.index("-vf") + 1])
        self.assertEqual(standard[standard.index("-ss") + 1], "1.000000")
        self.assertEqual(standard[standard.index("-t") + 1], "3.000000")

    async def test_engine_builds_versioned_manifest_and_downloadable_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "source.mp4"
            video.write_bytes(b"source-video")
            analysis = await make_analysis(video)
            extractor = FakeClipExtractor()
            storage = LocalArtifactStorage(root / "exports", root / "temporary")
            engine = ExportEngine(
                planner=ExportPlanner(),
                clip_extractor=extractor,
                package_builder=ZipPackageBuilder(),
                artifact_storage=storage,
            )

            result = await engine.export(
                analysis=analysis,
                source_filename="My Source.mp4",
                options=ExportOptions(
                    preset=ExportPresetName.HIGH_QUALITY,
                    top_k=2,
                ),
            )

            self.assertEqual(len(extractor.calls), 2)
            self.assertEqual(result.manifest.manifest_version, EXPORT_MANIFEST_VERSION)
            self.assertEqual(result.manifest.momentai_version, MOMENTAI_VERSION)
            self.assertEqual(result.manifest.pipeline_version, PIPELINE_VERSION)
            self.assertEqual(result.manifest.mie_version, MIE_VERSION)
            self.assertEqual(result.manifest.source_fingerprint, analysis.source_fingerprint)
            self.assertEqual(result.manifest.preset, ExportPresetName.HIGH_QUALITY)
            self.assertEqual(len(result.manifest.clips), 2)
            self.assertTrue(result.manifest.clips[0].contributions)
            self.assertTrue(result.manifest.clips[0].insights)
            self.assertTrue(storage.resolve_manifest(result.export_id).is_file())
            self.assertTrue(storage.resolve_package(result.export_id).is_file())
            self.assertFalse((root / "temporary" / result.export_id).exists())
            with ZipFile(result.package_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "manifest.json",
                        "checksums.sha256",
                        "clips/moment-001.mp4",
                        "clips/moment-002.mp4",
                    },
                )

    def test_storage_rejects_untrusted_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalArtifactStorage(Path(directory) / "exports", Path(directory) / "temp")
            with self.assertRaises(ExportArtifactNotFoundError):
                storage.resolve_package("../escape")


if __name__ == "__main__":
    unittest.main()

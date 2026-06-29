import tempfile
import unittest
from pathlib import Path

from backend.app.intelligence import create_default_engine
from backend.app.services.moment_pipeline_service import AnalysisResult, MomentPipelineService
from backend.app.services.scene_service import Scene, SceneDetectionResult
from backend.app.services.transcript_service import (
    MissingAudioError,
    TranscriptResult,
    TranscriptSegment,
)
from backend.app.services.video_service import VideoMetadata


def sample_metadata() -> VideoMetadata:
    return VideoMetadata(
        duration_seconds=12.0,
        width=1280,
        height=720,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        bitrate=2_000_000,
        rotation=None,
        file_size_bytes=1024,
    )


class FakeVideoService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def extract_metadata(self, _: Path) -> VideoMetadata:
        self.calls.append("video")
        return sample_metadata()


class FakeSceneService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def detect_scenes(self, _: Path) -> SceneDetectionResult:
        self.calls.append("scenes")
        return SceneDetectionResult(
            duration_seconds=12.0,
            scenes=(
                Scene(1, 0.0, 5.0, 5.0, Path("scene-001.jpg")),
                Scene(2, 5.0, 12.0, 7.0, Path("scene-002.jpg")),
            ),
        )


class FakeTranscriptService:
    def __init__(self, calls: list[str], fail: bool = False) -> None:
        self.calls = calls
        self.fail = fail

    async def transcribe(self, _: Path) -> TranscriptResult:
        self.calls.append("transcript")
        if self.fail:
            raise MissingAudioError("video has no audio")
        return TranscriptResult(
            language="en",
            duration_seconds=12.0,
            segments=(
                TranscriptSegment(0.0, 4.0, "opening transcript activity", 1),
                TranscriptSegment(7.0, 10.0, "second scene transcript", 2),
            ),
        )


class MomentPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_orders_real_service_outputs_before_engine(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "video.mp4"
            video_path.write_bytes(b"deterministic-video-content")
            pipeline = MomentPipelineService(
                video_service=FakeVideoService(calls),  # type: ignore[arg-type]
                scene_service=FakeSceneService(calls),  # type: ignore[arg-type]
                transcript_service=FakeTranscriptService(calls),  # type: ignore[arg-type]
                engine=create_default_engine(),
            )

            result = await pipeline.analyze(video_path)

        self.assertEqual(calls, ["video", "scenes", "transcript"])
        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(result.source_path, video_path.resolve())
        self.assertEqual(len(result.source_fingerprint), 64)
        self.assertEqual(result.transcript_result.language, "en")
        self.assertEqual(len(result.scene_result.scenes), 2)
        self.assertEqual(len(result.engine_result.moments), 2)
        self.assertFalse(result.diagnostics)
        signal_names = {
            contribution.signal_name
            for moment in result.engine_result.moments
            for contribution in moment.contributions
        }
        self.assertIn("scene.duration", signal_names)
        self.assertIn("transcript.coverage", signal_names)

    async def test_transcript_failure_degrades_to_scene_only_ranking(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "silent.mp4"
            video_path.write_bytes(b"silent-video-content")
            pipeline = MomentPipelineService(
                video_service=FakeVideoService(calls),  # type: ignore[arg-type]
                scene_service=FakeSceneService(calls),  # type: ignore[arg-type]
                transcript_service=FakeTranscriptService(calls, fail=True),  # type: ignore[arg-type]
                engine=create_default_engine(),
            )

            result = await pipeline.analyze(video_path)

        self.assertEqual(calls, ["video", "scenes", "transcript"])
        self.assertIsNone(result.transcript_result)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].stage, "transcript")
        self.assertEqual(result.diagnostics[0].status, "degraded")
        self.assertEqual(len(result.engine_result.moments), 2)
        signal_names = {
            contribution.signal_name
            for moment in result.engine_result.moments
            for contribution in moment.contributions
        }
        self.assertNotIn("transcript.coverage", signal_names)


if __name__ == "__main__":
    unittest.main()

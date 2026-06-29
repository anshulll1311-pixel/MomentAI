import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.app.analysis import (
    AnalysisCoordinator,
    AnalysisExecutionError,
    AnalysisStatus,
    ArtifactKind,
    InMemoryAnalysisRepository,
    LocalArtifactManager,
)
from backend.app.services.scene_service import Scene, SceneDetectionResult
from tests.test_semantic_foundation import analysis_result


class FakePipeline:
    def __init__(self, result, *, failure: Exception | None = None) -> None:
        self._result = result
        self._failure = failure
        self.calls = 0
        self.release = asyncio.Event()
        self.release.set()

    async def analyze(self, source_path: Path, profile_id: str = "default"):
        self.calls += 1
        await self.release.wait()
        if self._failure is not None:
            raise self._failure
        return replace(
            self._result,
            source_path=source_path.resolve(),
        )


class RecordingHook:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def analysis_started(self, record) -> None:
        self.events.append(("started", record.analysis_id))

    async def analysis_completed(self, record) -> None:
        self.events.append(("completed", record.analysis_id))

    async def analysis_failed(self, record) -> None:
        self.events.append(("failed", record.analysis_id))

    async def analysis_expired(self, record) -> None:
        self.events.append(("expired", record.analysis_id))


async def result_with_thumbnail(thumbnail_path: Path):
    result = await analysis_result()
    original = result.scene_result.scenes[0]
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    thumbnail_path.write_bytes(b"thumbnail")
    scene = Scene(
        id=original.id,
        start_seconds=original.start_seconds,
        end_seconds=original.end_seconds,
        duration_seconds=original.duration_seconds,
        thumbnail_path=thumbnail_path,
    )
    return replace(
        result,
        scene_result=SceneDetectionResult(
            duration_seconds=result.scene_result.duration_seconds,
            scenes=(scene,),
        ),
    )


class AnalysisRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.uploads = self.root / "uploads"
        self.thumbnails = self.root / "thumbnails"
        self.exports = self.root / "exports"
        self.uploads.mkdir()
        self.thumbnails.mkdir()
        self.exports.mkdir()
        result = await result_with_thumbnail(self.thumbnails / "scene-001.jpg")
        self.pipeline = FakePipeline(result)
        self.repository = InMemoryAnalysisRepository()
        self.hook = RecordingHook()
        self.coordinator = AnalysisCoordinator(
            repository=self.repository,
            artifact_manager=LocalArtifactManager(
                (self.uploads, self.thumbnails, self.exports)
            ),
            pipeline=self.pipeline,
            hooks=(self.hook,),
            configuration_version="test-v1",
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_equivalent_uploads_share_one_immutable_analysis(self) -> None:
        first_path = self.uploads / "first.mp4"
        duplicate_path = self.uploads / "duplicate.mp4"
        first_path.write_bytes(b"same-video")
        duplicate_path.write_bytes(b"same-video")

        first = await self.coordinator.create_or_reuse(
            source_path=first_path,
            source_filename="first.mp4",
        )
        second = await self.coordinator.create_or_reuse(
            source_path=duplicate_path,
            source_filename="duplicate.mp4",
        )

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.record.analysis_id, second.record.analysis_id)
        self.assertEqual(self.pipeline.calls, 1)
        self.assertFalse(duplicate_path.exists())
        self.assertIs(
            await self.coordinator.get_result(first.record.analysis_id),
            first.record.result,
        )
        self.assertEqual(
            [name for name, _ in self.hook.events],
            ["started", "completed"],
        )

    async def test_concurrent_equivalent_uploads_use_single_flight(self) -> None:
        first_path = self.uploads / "concurrent-a.mp4"
        second_path = self.uploads / "concurrent-b.mp4"
        first_path.write_bytes(b"concurrent-video")
        second_path.write_bytes(b"concurrent-video")
        self.pipeline.release.clear()

        first_task = asyncio.create_task(
            self.coordinator.create_or_reuse(
                source_path=first_path,
                source_filename="concurrent-a.mp4",
            )
        )
        await asyncio.sleep(0)
        second_task = asyncio.create_task(
            self.coordinator.create_or_reuse(
                source_path=second_path,
                source_filename="concurrent-b.mp4",
            )
        )
        await asyncio.sleep(0)
        self.pipeline.release.set()
        first, second = await asyncio.gather(first_task, second_task)

        self.assertEqual(self.pipeline.calls, 1)
        self.assertEqual(first.record.analysis_id, second.record.analysis_id)
        self.assertEqual({first.reused, second.reused}, {False, True})

    async def test_derived_artifacts_and_expiration_use_artifact_manager(self) -> None:
        source = self.uploads / "expire.mp4"
        source.write_bytes(b"expiring-video")
        created = await self.coordinator.create_or_reuse(
            source_path=source,
            source_filename="expire.mp4",
        )
        clip = self.exports / "clip.mp4"
        clip.write_bytes(b"clip")
        reference = self.coordinator.artifact_reference(ArtifactKind.EXPORTED_CLIP, clip)
        updated = await self.coordinator.add_artifacts(
            created.record.analysis_id,
            (reference,),
        )

        self.assertEqual(updated.artifacts.exported_clips, (reference,))
        expired = await self.coordinator.expire(created.record.analysis_id)

        self.assertIs(expired.status, AnalysisStatus.EXPIRED)
        self.assertFalse(source.exists())
        self.assertFalse(clip.exists())
        self.assertIn(("expired", created.record.analysis_id), self.hook.events)

    async def test_pipeline_failure_is_recorded_and_hooked(self) -> None:
        source = self.uploads / "broken.mp4"
        source.write_bytes(b"broken-video")
        self.pipeline._failure = RuntimeError("intentional pipeline failure")

        with self.assertRaises(AnalysisExecutionError) as raised:
            await self.coordinator.create_or_reuse(
                source_path=source,
                source_filename="broken.mp4",
            )

        record = await self.repository.get(raised.exception.analysis_id)
        self.assertIs(record.status, AnalysisStatus.FAILED)
        self.assertEqual(record.failure.error_type, "RuntimeError")
        self.assertIn(("failed", record.analysis_id), self.hook.events)


if __name__ == "__main__":
    unittest.main()

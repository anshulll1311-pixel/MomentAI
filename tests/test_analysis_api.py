import asyncio
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.analysis import (
    AnalysisArtifacts,
    AnalysisCoordinationResult,
    AnalysisRecord,
    AnalysisStatus,
    ArtifactKind,
    ArtifactReference,
)
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.semantic import ProviderRegistry, create_semantic_intelligence_service
from backend.app.services.scene_service import Scene, SceneDetectionResult
from backend.app.services.storage import StoredUpload
from tests.test_semantic_foundation import analysis_result


class FakeCoordinator:
    def __init__(self, record: AnalysisRecord) -> None:
        self.record = record
        self.create_calls = 0
        self.added_artifacts = ()

    async def create_or_reuse(self, **kwargs) -> AnalysisCoordinationResult:
        self.create_calls += 1
        return AnalysisCoordinationResult(record=self.record, reused=False)

    async def get_record(self, analysis_id: str) -> AnalysisRecord:
        return self.record

    async def get_result(self, analysis_id: str):
        return self.record.result

    def artifact_reference(self, kind: ArtifactKind, path: Path) -> ArtifactReference:
        return ArtifactReference(kind=kind, location=path.resolve().as_posix())

    def resolve_artifact(self, reference: ArtifactReference) -> Path:
        return Path(reference.location)

    async def add_artifacts(self, analysis_id: str, references) -> AnalysisRecord:
        self.added_artifacts = references
        return self.record


class FakeExportEngine:
    def __init__(self) -> None:
        self.analysis = None

    async def export(self, *, analysis, source_filename, options):
        self.analysis = analysis
        return SimpleNamespace(
            export_id="exp_test",
            profile_id=analysis.engine_result.profile_id,
            preset=options.preset,
            artifacts=(),
            manifest=SimpleNamespace(diagnostics=()),
            package_sha256="a" * 64,
        )


class AnalysisApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / "source.mp4"
        self.source.write_bytes(b"mock video")
        settings = get_settings()
        base_result = asyncio.run(analysis_result())
        scenes = tuple(
            Scene(
                id=scene.id,
                start_seconds=scene.start_seconds,
                end_seconds=scene.end_seconds,
                duration_seconds=scene.duration_seconds,
                thumbnail_path=(
                    settings.thumbnail_dir
                    / "scenes"
                    / "api-test"
                    / f"scene-{scene.id:03d}.jpg"
                ),
            )
            for scene in base_result.scene_result.scenes
        )
        result = replace(
            base_result,
            source_path=self.source,
            scene_result=SceneDetectionResult(
                duration_seconds=base_result.scene_result.duration_seconds,
                scenes=scenes,
            ),
        )
        now = datetime.now(UTC)
        self.preview = settings.thumbnail_dir / "api-test" / "middle.jpg"
        self.preview.parent.mkdir(parents=True, exist_ok=True)
        self.preview.write_bytes(b"preview")
        source_reference = ArtifactReference(
            kind=ArtifactKind.SOURCE_MEDIA,
            location=self.source.resolve().as_posix(),
        )
        self.record = AnalysisRecord(
            analysis_id="ana_test",
            analysis_key="k" * 64,
            source_fingerprint="a" * 64,
            source_filename="source.mp4",
            profile_id="default",
            status=AnalysisStatus.READY,
            artifacts=AnalysisArtifacts(
                source_media=source_reference,
                preview_assets=(
                    ArtifactReference(
                        kind=ArtifactKind.PREVIEW,
                        location=self.preview.resolve().as_posix(),
                    ),
                ),
            ),
            created_at=now,
            updated_at=now,
            completed_at=now,
            result=result,
        )
        self.coordinator = FakeCoordinator(self.record)
        self.stored = StoredUpload(
            original_filename="source.mp4",
            filename="source-stored.mp4",
            size_bytes=self.source.stat().st_size,
            content_type="video/mp4",
            path=self.source,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.preview.unlink(missing_ok=True)
        self.preview.parent.rmdir()
        self.temporary.cleanup()

    def test_analysis_creation_status_and_moments_routes(self) -> None:
        with (
            patch(
                "backend.app.api.routes.analyses.get_analysis_coordinator",
                return_value=self.coordinator,
            ),
            patch(
                "backend.app.api.routes.analyses.store_upload",
                new=AsyncMock(return_value=self.stored),
            ),
        ):
            created = self.client.post(
                "/api/v1/analyses",
                files={"file": ("source.mp4", b"mock video", "video/mp4")},
            )
            status_response = self.client.get("/api/v1/analyses/ana_test")
            moments = self.client.get("/api/v1/analyses/ana_test/moments")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["analysis_id"], "ana_test")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "ready")
        self.assertEqual(moments.status_code, 200)
        self.assertEqual(len(moments.json()["moments"]), 2)

    def test_semantic_and_export_consume_repository_result(self) -> None:
        semantic_service = create_semantic_intelligence_service(ProviderRegistry())
        export_engine = FakeExportEngine()
        with (
            patch(
                "backend.app.api.routes.analyses.get_analysis_coordinator",
                return_value=self.coordinator,
            ),
            patch(
                "backend.app.api.routes.analyses.get_semantic_service",
                return_value=semantic_service,
            ),
            patch(
                "backend.app.api.routes.analyses.build_export_engine",
                return_value=export_engine,
            ),
        ):
            semantic = self.client.post(
                "/api/v1/analyses/ana_test/semantic",
                json={"provider_id": "auto"},
            )
            exported = self.client.post(
                "/api/v1/analyses/ana_test/export",
                json={"preset": "preview", "top_k": 2},
            )

        self.assertEqual(semantic.status_code, 200)
        self.assertEqual(semantic.json()["status"], "degraded")
        self.assertEqual(exported.status_code, 201)
        self.assertEqual(exported.json()["export_id"], "exp_test")
        self.assertIs(export_engine.analysis, self.record.result)

    def test_legacy_moments_endpoint_preserves_response_and_uses_coordinator(self) -> None:
        with (
            patch(
                "backend.app.api.routes.moments.get_analysis_coordinator",
                return_value=self.coordinator,
            ),
            patch(
                "backend.app.api.routes.moments.store_upload",
                new=AsyncMock(return_value=self.stored),
            ),
        ):
            response = self.client.post(
                "/api/v1/moments",
                files={"file": ("source.mp4", b"mock video", "video/mp4")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(self.coordinator.create_calls, 1)

    def test_legacy_projection_endpoints_preserve_response_contracts(self) -> None:
        targets = (
            ("uploads", "/api/v1/uploads", "metadata"),
            ("analyze", "/api/v1/analyze", "thumbnail"),
            ("scenes", "/api/v1/scenes", "scenes"),
            ("transcript", "/api/v1/transcript", "segments"),
        )
        for module, url, expected_field in targets:
            with self.subTest(url=url):
                with (
                    patch(
                        f"backend.app.api.routes.{module}.get_analysis_coordinator",
                        return_value=self.coordinator,
                    ),
                    patch(
                        f"backend.app.api.routes.{module}.store_upload",
                        new=AsyncMock(return_value=self.stored),
                    ),
                ):
                    response = self.client.post(
                        url,
                        files={"file": ("source.mp4", b"mock video", "video/mp4")},
                    )
                self.assertEqual(response.status_code, 201)
                self.assertIn(expected_field, response.json())

    def test_legacy_export_uses_coordinator_and_preserves_response(self) -> None:
        export_engine = FakeExportEngine()
        with (
            patch(
                "backend.app.api.routes.exports.get_analysis_coordinator",
                return_value=self.coordinator,
            ),
            patch(
                "backend.app.api.routes.exports.store_upload",
                new=AsyncMock(return_value=self.stored),
            ),
            patch(
                "backend.app.api.routes.exports.build_export_engine",
                return_value=export_engine,
            ),
        ):
            response = self.client.post(
                "/api/v1/exports",
                files={"file": ("source.mp4", b"mock video", "video/mp4")},
                data={"preset": "standard", "top_k": "2"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["export_id"], "exp_test")
        self.assertIs(export_engine.analysis, self.record.result)


if __name__ == "__main__":
    unittest.main()

import errno
import json
import os
import re
import shutil
from dataclasses import replace
from pathlib import Path

from backend.app.exporting.errors import (
    ExportArtifactNotFoundError,
    ExportStorageError,
    InsufficientExportStorageError,
)
from backend.app.exporting.models import ClipArtifact, ExportManifest

EXPORT_ID_PATTERN = re.compile(r"^exp_[0-9a-f]{32}$")
CLIP_ID_PATTERN = re.compile(r"^moment-[0-9]{3}$")


class LocalArtifactStorage:
    """Own local export paths and publish artifacts atomically."""

    def __init__(self, export_directory: Path, temporary_directory: Path) -> None:
        self._export_directory = export_directory.resolve()
        self._temporary_directory = temporary_directory.resolve()

    def prepare(self, export_id: str) -> None:
        self._validate_export_id(export_id)
        try:
            self.clips_directory(export_id).mkdir(parents=True, exist_ok=False)
            self.temporary_export_directory(export_id).mkdir(parents=True, exist_ok=False)
        except OSError as error:
            shutil.rmtree(self._contained(self._export_directory, export_id), ignore_errors=True)
            shutil.rmtree(self._contained(self._temporary_directory, export_id), ignore_errors=True)
            self._raise_storage_error("Export workspace could not be created.", error)

    def clips_directory(self, export_id: str) -> Path:
        self._validate_export_id(export_id)
        return self._contained(self._export_directory, export_id, "clips")

    def temporary_export_directory(self, export_id: str) -> Path:
        self._validate_export_id(export_id)
        return self._contained(self._temporary_directory, export_id)

    def temporary_clip_path(self, export_id: str, clip_id: str) -> Path:
        self._validate_clip_id(clip_id)
        return self._contained(
            self.temporary_export_directory(export_id),
            f"{clip_id}.part.mp4",
        )

    def final_clip_path(self, export_id: str, clip_id: str) -> Path:
        self._validate_clip_id(clip_id)
        return self._contained(self.clips_directory(export_id), f"{clip_id}.mp4")

    def publish_clip(self, export_id: str, artifact: ClipArtifact) -> ClipArtifact:
        destination = self.final_clip_path(export_id, artifact.spec.clip_id)
        self._atomic_replace(artifact.path, destination)
        return replace(artifact, path=destination)

    def write_manifest(self, export_id: str, manifest: ExportManifest) -> Path:
        export_directory = self._contained(self._export_directory, export_id)
        temporary_path = self._contained(export_directory, "manifest.part.json")
        final_path = self._contained(export_directory, "manifest.json")
        try:
            temporary_path.write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._atomic_replace(temporary_path, final_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            self._raise_storage_error("Export manifest could not be stored.", error)
        return final_path

    def write_checksums(self, export_id: str, artifacts: tuple[ClipArtifact, ...]) -> Path:
        export_directory = self._contained(self._export_directory, export_id)
        temporary_path = self._contained(export_directory, "checksums.part.sha256")
        final_path = self._contained(export_directory, "checksums.sha256")
        content = "".join(
            f"{artifact.sha256}  clips/{artifact.path.name}\n" for artifact in artifacts
        )
        try:
            temporary_path.write_text(content, encoding="utf-8")
            self._atomic_replace(temporary_path, final_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            self._raise_storage_error("Export checksums could not be stored.", error)
        return final_path

    def temporary_package_path(self, export_id: str) -> Path:
        return self._contained(
            self.temporary_export_directory(export_id),
            "package.part.zip",
        )

    def final_package_path(self, export_id: str) -> Path:
        self._validate_export_id(export_id)
        return self._contained(
            self._export_directory,
            export_id,
            f"momentai-export-{export_id}.zip",
        )

    def publish_package(self, export_id: str, temporary_path: Path) -> Path:
        destination = self.final_package_path(export_id)
        self._atomic_replace(temporary_path, destination)
        return destination

    def resolve_clip(self, export_id: str, clip_id: str) -> Path:
        path = self.final_clip_path(export_id, clip_id)
        return self._require_file(path)

    def resolve_manifest(self, export_id: str) -> Path:
        self._validate_export_id(export_id)
        return self._require_file(self._contained(self._export_directory, export_id, "manifest.json"))

    def resolve_package(self, export_id: str) -> Path:
        return self._require_file(self.final_package_path(export_id))

    def cleanup_temporary(self, export_id: str) -> None:
        shutil.rmtree(self.temporary_export_directory(export_id), ignore_errors=True)

    def cleanup_failed_export(self, export_id: str) -> None:
        shutil.rmtree(self._contained(self._export_directory, export_id), ignore_errors=True)
        shutil.rmtree(self.temporary_export_directory(export_id), ignore_errors=True)

    @staticmethod
    def _require_file(path: Path) -> Path:
        if not path.is_file():
            raise ExportArtifactNotFoundError("The requested export artifact was not found.")
        return path

    @staticmethod
    def _validate_export_id(export_id: str) -> None:
        if not EXPORT_ID_PATTERN.fullmatch(export_id):
            raise ExportArtifactNotFoundError("The requested export was not found.")

    @staticmethod
    def _validate_clip_id(clip_id: str) -> None:
        if not CLIP_ID_PATTERN.fullmatch(clip_id):
            raise ExportArtifactNotFoundError("The requested export clip was not found.")

    @staticmethod
    def _contained(root: Path, *parts: str) -> Path:
        candidate = root.joinpath(*parts).resolve()
        if candidate != root and root not in candidate.parents:
            raise ExportStorageError("An export artifact path escaped its storage root.")
        return candidate

    def _atomic_replace(self, source: Path, destination: Path) -> None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
        except OSError as error:
            self._raise_storage_error("An export artifact could not be published.", error)

    @staticmethod
    def _raise_storage_error(message: str, error: OSError) -> None:
        if error.errno == errno.ENOSPC:
            raise InsufficientExportStorageError("Local export storage is full.") from error
        raise ExportStorageError(message) from error

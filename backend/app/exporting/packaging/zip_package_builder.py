import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from backend.app.exporting.errors import ExportPackageError
from backend.app.exporting.models import ClipArtifact


class PackageBuilder(ABC):
    @abstractmethod
    async def build(
        self,
        output_path: Path,
        manifest_path: Path,
        checksums_path: Path,
        artifacts: tuple[ClipArtifact, ...],
    ) -> None:
        """Build one downloadable export package."""


class ZipPackageBuilder(PackageBuilder):
    async def build(
        self,
        output_path: Path,
        manifest_path: Path,
        checksums_path: Path,
        artifacts: tuple[ClipArtifact, ...],
    ) -> None:
        try:
            await asyncio.to_thread(
                _build_zip,
                output_path,
                manifest_path,
                checksums_path,
                artifacts,
            )
        except (OSError, BadZipFile) as error:
            output_path.unlink(missing_ok=True)
            raise ExportPackageError("The downloadable export package could not be built.") from error


def _build_zip(
    output_path: Path,
    manifest_path: Path,
    checksums_path: Path,
    artifacts: tuple[ClipArtifact, ...],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    with ZipFile(output_path, mode="x", compression=ZIP_STORED, allowZip64=True) as archive:
        archive.write(manifest_path, arcname="manifest.json")
        archive.write(checksums_path, arcname="checksums.sha256")
        for artifact in artifacts:
            archive.write(artifact.path, arcname=f"clips/{artifact.path.name}")
    with ZipFile(output_path, mode="r") as archive:
        if archive.testzip() is not None:
            raise BadZipFile("package checksum validation failed")

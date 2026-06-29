import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.exporting.ffmpeg.command_builder import FFmpegCommandBuilder
from backend.app.exporting.ffmpeg.output_validator import FFprobeOutputValidator
from backend.app.exporting.ffmpeg.process_runner import FFmpegProcessRunner
from backend.app.exporting.models import ClipArtifact, ClipSpec, ExportPreset


class ClipExtractor(ABC):
    @abstractmethod
    async def extract(
        self,
        source_path: Path,
        spec: ClipSpec,
        preset: ExportPreset,
        output_path: Path,
    ) -> ClipArtifact:
        """Extract and validate one clip into a temporary output path."""


class FFmpegClipExtractor(ClipExtractor):
    def __init__(
        self,
        command_builder: FFmpegCommandBuilder,
        process_runner: FFmpegProcessRunner,
        output_validator: FFprobeOutputValidator,
    ) -> None:
        self._command_builder = command_builder
        self._process_runner = process_runner
        self._output_validator = output_validator

    async def extract(
        self,
        source_path: Path,
        spec: ClipSpec,
        preset: ExportPreset,
        output_path: Path,
    ) -> ClipArtifact:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        command = self._command_builder.build(source_path, output_path, spec, preset)
        try:
            await self._process_runner.run(command)
            metadata = await self._output_validator.validate(
                output_path,
                expected_duration_seconds=spec.duration_seconds,
            )
            checksum = await _sha256_file(output_path)
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise
        return ClipArtifact(
            spec=spec,
            path=output_path,
            metadata=metadata,
            sha256=checksum,
        )


async def _sha256_file(path: Path) -> str:
    import asyncio

    return await asyncio.to_thread(_sha256_file_sync, path)


def _sha256_file_sync(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

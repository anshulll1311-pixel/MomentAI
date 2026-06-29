import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.video_service import VideoMetadata, VideoService

logger = logging.getLogger(__name__)


class VideoAnalyzerError(RuntimeError):
    """Base error for video analysis failures."""


class FFmpegUnavailableError(VideoAnalyzerError):
    """Raised when FFmpeg cannot be started."""


class AnalysisTimeoutError(VideoAnalyzerError):
    """Raised when thumbnail generation exceeds its timeout."""


class ThumbnailGenerationError(VideoAnalyzerError):
    """Raised when FFmpeg cannot create a thumbnail."""


@dataclass(frozen=True, slots=True)
class VideoAnalysis:
    metadata: VideoMetadata
    thumbnail_path: Path


class VideoAnalyzer:
    """Coordinate metadata extraction and middle-frame thumbnail generation."""

    def __init__(
        self,
        video_service: VideoService,
        thumbnail_directory: Path,
        ffmpeg_binary: str = "ffmpeg",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._video_service = video_service
        self._thumbnail_directory = thumbnail_directory
        self._ffmpeg_binary = ffmpeg_binary
        self._timeout_seconds = timeout_seconds

    async def analyze(self, video_path: Path) -> VideoAnalysis:
        metadata = await self._video_service.extract_metadata(video_path)
        thumbnail_path = await self.generate_thumbnail(
            video_path=video_path,
            timestamp_seconds=metadata.duration_seconds / 2,
        )
        return VideoAnalysis(metadata=metadata, thumbnail_path=thumbnail_path)

    async def generate_thumbnail(
        self,
        video_path: Path,
        timestamp_seconds: float,
    ) -> Path:
        """Generate a reusable thumbnail without probing metadata again."""

        self._thumbnail_directory.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self._thumbnail_directory / f"{video_path.stem}.jpg"
        command = (
            self._ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp_seconds:.6f}",
            "-i",
            str(video_path.resolve()),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(thumbnail_path.resolve()),
        )

        logger.info(
            "Generating middle thumbnail for %s at %.3f seconds",
            video_path.name,
            timestamp_seconds,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            logger.exception("Unable to start FFmpeg executable: %s", self._ffmpeg_binary)
            raise FFmpegUnavailableError("Video thumbnail service is unavailable.") from error

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            thumbnail_path.unlink(missing_ok=True)
            logger.warning("FFmpeg timed out for %s", video_path.name)
            raise AnalysisTimeoutError("Video thumbnail generation timed out.") from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            thumbnail_path.unlink(missing_ok=True)
            raise

        if process.returncode != 0:
            thumbnail_path.unlink(missing_ok=True)
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "FFmpeg thumbnail generation failed for %s: %s",
                video_path.name,
                diagnostic[:500] or "unknown FFmpeg error",
            )
            raise ThumbnailGenerationError("A thumbnail could not be generated for this video.")

        try:
            thumbnail_size = thumbnail_path.stat().st_size
        except OSError as error:
            thumbnail_path.unlink(missing_ok=True)
            raise ThumbnailGenerationError("The generated thumbnail could not be read.") from error

        if thumbnail_size == 0:
            thumbnail_path.unlink(missing_ok=True)
            raise ThumbnailGenerationError("FFmpeg generated an empty thumbnail.")

        logger.info("Generated thumbnail %s (%s bytes)", thumbnail_path.name, thumbnail_size)
        return thumbnail_path


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()

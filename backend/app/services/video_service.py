import asyncio
import json
import logging
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VideoServiceError(RuntimeError):
    """Base error for video metadata processing failures."""


class VideoToolUnavailableError(VideoServiceError):
    """Raised when ffprobe cannot be started."""


class VideoProbeTimeoutError(VideoServiceError):
    """Raised when ffprobe exceeds its configured timeout."""


class InvalidVideoError(VideoServiceError):
    """Raised when a file is not a readable video."""


class VideoProcessingError(VideoServiceError):
    """Raised when metadata processing fails unexpectedly."""


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    file_size_bytes: int


class VideoService:
    """Extract video metadata through a safely invoked ffprobe process."""

    def __init__(self, ffprobe_binary: str = "ffprobe", timeout_seconds: float = 30.0) -> None:
        self._ffprobe_binary = ffprobe_binary
        self._timeout_seconds = timeout_seconds

    async def extract_metadata(self, video_path: Path) -> VideoMetadata:
        path = video_path.resolve()
        if not path.is_file():
            raise VideoProcessingError("The stored video file could not be found.")

        logger.info("Probing video metadata: %s", path.name)
        command = (
            self._ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration",
            "-of",
            "json",
            str(path),
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            logger.exception("Unable to start ffprobe executable: %s", self._ffprobe_binary)
            raise VideoToolUnavailableError("Video metadata service is unavailable.") from error

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            logger.warning("ffprobe timed out for %s", path.name)
            raise VideoProbeTimeoutError("Video metadata extraction timed out.") from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            raise

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "ffprobe rejected %s: %s",
                path.name,
                diagnostic[:500] or "unknown ffprobe error",
            )
            raise InvalidVideoError("The uploaded file is not a valid or readable video.")

        try:
            probe_data = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.exception("ffprobe returned malformed JSON for %s", path.name)
            raise VideoProcessingError("Video metadata could not be decoded.") from error

        metadata = self._parse_metadata(probe_data, path)
        logger.info(
            "Video metadata extracted for %s: %sx%s, %.3f fps, %.3f seconds",
            path.name,
            metadata.width,
            metadata.height,
            metadata.fps,
            metadata.duration_seconds,
        )
        return metadata

    @staticmethod
    def _parse_metadata(probe_data: dict[str, Any], path: Path) -> VideoMetadata:
        streams = probe_data.get("streams")
        if not isinstance(streams, list):
            raise InvalidVideoError("The uploaded file does not contain readable media streams.")

        video_stream = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ),
            None,
        )
        if not isinstance(video_stream, dict):
            raise InvalidVideoError("The uploaded file does not contain a video stream.")

        audio_stream = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "audio"
            ),
            None,
        )
        format_data = probe_data.get("format")
        if not isinstance(format_data, dict):
            format_data = {}

        duration = _positive_float(format_data.get("duration"))
        if duration is None:
            duration = _positive_float(video_stream.get("duration"))

        width = _positive_int(video_stream.get("width"))
        height = _positive_int(video_stream.get("height"))
        fps = _frame_rate(video_stream.get("avg_frame_rate"))
        if fps is None:
            fps = _frame_rate(video_stream.get("r_frame_rate"))

        video_codec = video_stream.get("codec_name")
        if duration is None or width is None or height is None or fps is None or not video_codec:
            raise InvalidVideoError("Required video metadata is missing or invalid.")

        audio_codec = None
        if isinstance(audio_stream, dict) and audio_stream.get("codec_name"):
            audio_codec = str(audio_stream["codec_name"])

        try:
            file_size = path.stat().st_size
        except OSError as error:
            raise VideoProcessingError("The stored video size could not be read.") from error

        return VideoMetadata(
            duration_seconds=duration,
            width=width,
            height=height,
            fps=fps,
            video_codec=str(video_codec),
            audio_codec=audio_codec,
            file_size_bytes=file_size,
        )


def _positive_float(value: object) -> float | None:
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _positive_int(value: object) -> int | None:
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _frame_rate(value: object) -> float | None:
    try:
        result = float(Fraction(str(value)))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return result if math.isfinite(result) and result > 0 else None


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()

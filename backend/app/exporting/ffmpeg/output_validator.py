import asyncio
import json
import math
from pathlib import Path
from typing import Any

from backend.app.exporting.errors import (
    ClipValidationError,
    ExportTimeoutError,
    ExportToolUnavailableError,
)
from backend.app.exporting.models import ClipMediaMetadata


class FFprobeOutputValidator:
    """Verify that an exported clip is readable and matches its planned duration."""

    def __init__(self, ffprobe_binary: str = "ffprobe", timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._ffprobe_binary = ffprobe_binary
        self._timeout_seconds = timeout_seconds

    async def validate(
        self,
        path: Path,
        expected_duration_seconds: float,
    ) -> ClipMediaMetadata:
        if not path.is_file() or path.stat().st_size <= 0:
            raise ClipValidationError("FFmpeg did not create a readable clip file.")
        command = (
            self._ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path.resolve()),
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            raise ExportToolUnavailableError("FFprobe export validation is unavailable.") from error

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            raise ExportTimeoutError("Exported clip validation timed out.") from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            raise

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            raise ClipValidationError(
                diagnostic[:500] or "The exported clip is not readable."
            )
        try:
            payload = json.loads(stdout)
            metadata = _parse_metadata(payload, path)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise ClipValidationError("FFprobe returned invalid clip metadata.") from error

        tolerance = max(0.75, expected_duration_seconds * 0.1)
        if abs(metadata.duration_seconds - expected_duration_seconds) > tolerance:
            raise ClipValidationError("The exported clip duration is outside the allowed tolerance.")
        return metadata


def _parse_metadata(payload: dict[str, Any], path: Path) -> ClipMediaMetadata:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ValueError("missing streams")
    video = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"),
        None,
    )
    if not isinstance(video, dict):
        raise ValueError("missing video stream")
    audio = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
        None,
    )
    format_data = payload.get("format")
    if not isinstance(format_data, dict):
        raise ValueError("missing format")
    duration = float(format_data["duration"])
    width = int(video["width"])
    height = int(video["height"])
    video_codec = str(video["codec_name"])
    if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
        raise ValueError("invalid media values")
    audio_codec = None
    if isinstance(audio, dict) and audio.get("codec_name"):
        audio_codec = str(audio["codec_name"])
    return ClipMediaMetadata(
        duration_seconds=duration,
        width=width,
        height=height,
        video_codec=video_codec,
        audio_codec=audio_codec,
        size_bytes=path.stat().st_size,
    )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()

import asyncio
import logging

from backend.app.exporting.errors import (
    ExportTimeoutError,
    ExportToolUnavailableError,
    FFmpegExecutionError,
)

logger = logging.getLogger(__name__)


class FFmpegProcessRunner:
    """Run one FFmpeg command with timeout and cancellation safety."""

    def __init__(self, timeout_seconds: float = 300.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    async def run(self, command: tuple[str, ...]) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            logger.exception("Unable to start FFmpeg")
            raise ExportToolUnavailableError("FFmpeg export service is unavailable.") from error

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            raise ExportTimeoutError("Clip extraction timed out.") from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            raise

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            logger.warning("FFmpeg export failed: %s", diagnostic[:500])
            raise FFmpegExecutionError(
                diagnostic[:500] or "FFmpeg could not extract the requested clip."
            )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()

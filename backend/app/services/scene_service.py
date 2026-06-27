import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.video_service import VideoService

logger = logging.getLogger(__name__)
PTS_TIME_PATTERN = re.compile(r"pts_time:([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


class SceneServiceError(RuntimeError):
    """Base error for scene detection failures."""


class SceneToolUnavailableError(SceneServiceError):
    """Raised when FFmpeg cannot be started."""


class SceneTimeoutError(SceneServiceError):
    """Raised when an FFmpeg scene operation times out."""


class SceneDetectionError(SceneServiceError):
    """Raised when scene boundaries cannot be detected."""


class SceneThumbnailError(SceneServiceError):
    """Raised when a scene thumbnail cannot be generated."""


class _FFmpegCommandError(RuntimeError):
    def __init__(self, diagnostic: str) -> None:
        super().__init__(diagnostic)
        self.diagnostic = diagnostic


@dataclass(frozen=True, slots=True)
class Scene:
    id: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    thumbnail_path: Path


@dataclass(frozen=True, slots=True)
class SceneDetectionResult:
    duration_seconds: float
    scenes: tuple[Scene, ...]


class SceneService:
    """Detect scene boundaries and generate one middle thumbnail per scene."""

    def __init__(
        self,
        video_service: VideoService,
        thumbnail_directory: Path,
        ffmpeg_binary: str = "ffmpeg",
        threshold: float = 0.3,
        minimum_scene_duration_seconds: float = 0.5,
        detection_timeout_seconds: float = 120.0,
        thumbnail_timeout_seconds: float = 30.0,
    ) -> None:
        self._video_service = video_service
        self._thumbnail_directory = thumbnail_directory
        self._ffmpeg_binary = ffmpeg_binary
        self._threshold = threshold
        self._minimum_scene_duration_seconds = minimum_scene_duration_seconds
        self._detection_timeout_seconds = detection_timeout_seconds
        self._thumbnail_timeout_seconds = thumbnail_timeout_seconds

    async def detect_scenes(self, video_path: Path) -> SceneDetectionResult:
        metadata = await self._video_service.extract_metadata(video_path)
        cut_times = await self._detect_cut_times(video_path, metadata.duration_seconds)
        boundaries = self._build_boundaries(cut_times, metadata.duration_seconds)
        scene_directory = self._thumbnail_directory / "scenes" / video_path.stem

        logger.info("Detected %s scene boundaries for %s", len(boundaries) - 2, video_path.name)
        try:
            scenes = []
            for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
                thumbnail_path = scene_directory / f"scene-{index:03d}.jpg"
                await self._generate_thumbnail(
                    video_path=video_path,
                    timestamp_seconds=start + ((end - start) / 2),
                    output_path=thumbnail_path,
                )
                scenes.append(
                    Scene(
                        id=index,
                        start_seconds=start,
                        end_seconds=end,
                        duration_seconds=end - start,
                        thumbnail_path=thumbnail_path,
                    )
                )
        except Exception:
            shutil.rmtree(scene_directory, ignore_errors=True)
            raise

        logger.info("Created %s scenes for %s", len(scenes), video_path.name)
        return SceneDetectionResult(
            duration_seconds=metadata.duration_seconds,
            scenes=tuple(scenes),
        )

    async def _detect_cut_times(self, video_path: Path, duration_seconds: float) -> list[float]:
        scene_filter = f"select='gt(scene,{self._threshold:.6f})',showinfo"
        command = (
            self._ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "info",
            "-i",
            str(video_path.resolve()),
            "-vf",
            scene_filter,
            "-an",
            "-f",
            "null",
            "-",
        )

        logger.info("Detecting scenes in %s with threshold %.3f", video_path.name, self._threshold)
        try:
            stderr = await self._run_ffmpeg(
                command,
                timeout_seconds=self._detection_timeout_seconds,
                timeout_message="Scene detection timed out.",
            )
        except _FFmpegCommandError as error:
            logger.warning(
                "Scene detection failed for %s: %s",
                video_path.name,
                error.diagnostic[:500],
            )
            raise SceneDetectionError("Scene changes could not be detected in this video.") from error

        timestamps = {
            float(match.group(1))
            for match in PTS_TIME_PATTERN.finditer(stderr)
            if 0 < float(match.group(1)) < duration_seconds
        }
        return sorted(timestamps)

    def _build_boundaries(self, cut_times: list[float], duration_seconds: float) -> list[float]:
        boundaries = [0.0]
        for cut_time in cut_times:
            if cut_time - boundaries[-1] < self._minimum_scene_duration_seconds:
                continue
            if duration_seconds - cut_time < self._minimum_scene_duration_seconds:
                continue
            boundaries.append(cut_time)
        boundaries.append(duration_seconds)
        return boundaries

    async def _generate_thumbnail(
        self,
        video_path: Path,
        timestamp_seconds: float,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = (
            self._ffmpeg_binary,
            "-nostdin",
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
            str(output_path.resolve()),
        )

        try:
            await self._run_ffmpeg(
                command,
                timeout_seconds=self._thumbnail_timeout_seconds,
                timeout_message="Scene thumbnail generation timed out.",
            )
        except _FFmpegCommandError as error:
            output_path.unlink(missing_ok=True)
            logger.warning(
                "Scene thumbnail generation failed for %s: %s",
                video_path.name,
                error.diagnostic[:500],
            )
            raise SceneThumbnailError("A scene thumbnail could not be generated.") from error

        try:
            thumbnail_size = output_path.stat().st_size
        except OSError as error:
            output_path.unlink(missing_ok=True)
            raise SceneThumbnailError("A generated scene thumbnail could not be read.") from error
        if thumbnail_size == 0:
            output_path.unlink(missing_ok=True)
            raise SceneThumbnailError("FFmpeg generated an empty scene thumbnail.")

    async def _run_ffmpeg(
        self,
        command: tuple[str, ...],
        timeout_seconds: float,
        timeout_message: str,
    ) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            logger.exception("Unable to start FFmpeg executable: %s", self._ffmpeg_binary)
            raise SceneToolUnavailableError("Scene detection service is unavailable.") from error

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            logger.warning("FFmpeg scene operation timed out")
            raise SceneTimeoutError(timeout_message) from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            raise

        diagnostic = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise _FFmpegCommandError(diagnostic or "unknown FFmpeg error")
        return diagnostic


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()
